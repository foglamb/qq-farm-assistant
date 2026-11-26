@file:Suppress("UNCHECKED_CAST")

package moe.fuqiuluo.api

import CONFIG
import com.tencent.mobileqq.channel.SsoPacket
import com.tencent.mobileqq.qsec.qsecurity.QSec
import com.tencent.mobileqq.sign.QQSecuritySign
import io.ktor.server.application.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import io.ktor.util.pipeline.*
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.jsonPrimitive
import moe.fuqiuluo.comm.EnvData
import moe.fuqiuluo.ext.*
import moe.fuqiuluo.unidbg.session.SessionManager
import java.util.Locale.getDefault

fun Routing.sign() {
    get("/sign") {
        val uin = fetchGet("uin")!!
        val qua = fetchGet("qua", CONFIG.protocol.qua)!!
        val cmd = fetchGet("cmd")!!
        val seq = fetchGet("seq")!!.toInt()
        val buffer = fetchGet("buffer")!!.hex2ByteArray()
        val qimei36 = fetchGet("qimei36", def = "")!!

        val androidId = fetchGet("android_id", def = "")!!
        val guid = fetchGet("guid", def = "")!!

        requestSign(cmd, uin, qua, seq, buffer, qimei36, androidId, guid)
    }

    post("/sign") {
        val req = call.receive<SignRequest>()
        val uin = req.uin.jsonPrimitive.content
        val qua = req.qua ?: CONFIG.protocol.qua
        require(qua == CONFIG.protocol.qua) { "QUA must match ${CONFIG.protocol.qua}" }
        require(req.version == null || req.version == CONFIG.protocol.version) {
            "version must match ${CONFIG.protocol.version}"
        }
        val cmd = req.cmd
        val seq = req.seq.jsonPrimitive.content.toInt()
        val buffer = req.buffer.hex2ByteArray()
        val qimei36 = req.qimei36 ?: ""
        val androidId = req.android_id ?: ""
        val guid = req.guid ?: ""

        requestSign(cmd, uin, qua, seq, buffer, qimei36, androidId, guid)
    }
}

@Serializable
private data class Sign(
    val token: String,
    val extra: String,
    val sign: String,
    val o3did: String,
    val requestCallback: List<SsoPacket>
)

private suspend fun PipelineContext<Unit, ApplicationCall>.requestSign(
    cmd: String,
    uin: String,
    qua: String,
    seq: Int,
    buffer: ByteArray,
    qimei36: String,
    androidId: String,
    guid: String
) {
    val session = initSession(uin.toLong()) ?: run {
        if (guid.isEmpty()) {
            throw MissingKeyError
        }

        SessionManager.register(
            EnvData(
                uin.toLong(),
                androidId,
                guid.lowercase(),
                qimei36,
                qua,
                CONFIG.protocol.version,
                CONFIG.protocol.code
            )
        )
        findSession(uin.toLong())
    }
    val vm = session.vm
    if (qimei36.isNotEmpty()) {
        vm.global["qimei36"] = qimei36
    }

    val list = arrayListOf<SsoPacket>()
    lateinit var o3did: String

    val sign = session.withLock {
        vm.global["est_data"] = QSec.getEst(vm)
        QQSecuritySign.getSign(vm, qua, cmd, buffer, seq, uin).value.also {
            o3did = vm.global["o3did"] as? String ?: ""
            val requiredPacket = vm.global["PACKET"] as ArrayList<SsoPacket>
            list.addAll(requiredPacket)
            requiredPacket.clear()
        }
    }

    call.respond(
        APIResult(
            0, "success", Sign(
                sign.token.toHexString().uppercase(getDefault()),
                sign.extra.toHexString().uppercase(getDefault()),
                sign.sign.toHexString().uppercase(getDefault()), o3did.uppercase(getDefault()), list
            )
        )
    )
}

@Serializable
data class SignRequest(
    val cmd: String,
    val buffer: String,
    // JsonPrimitive.content accepts both legacy strings and Lagrange's JSON numbers.
    val uin: JsonElement,
    val seq: JsonElement,
    val qua: String? = null,
    val version: String? = null,
    val qimei36: String? = null,
    val android_id: String? = null,
    val guid: String? = null
)