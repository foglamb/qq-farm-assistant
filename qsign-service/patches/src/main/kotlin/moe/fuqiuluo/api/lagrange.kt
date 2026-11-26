package moe.fuqiuluo.api

import CONFIG
import com.tencent.crypt.Crypt
import com.tencent.mobileqq.qsec.qsecdandelionsdk.Dandelion
import com.tencent.mobileqq.qsec.qsecurity.QSec
import com.tencent.secprotocol.ByteData
import io.ktor.server.application.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.jsonPrimitive
import moe.fuqiuluo.comm.EnvData
import moe.fuqiuluo.ext.toHexString
import moe.fuqiuluo.unidbg.session.Session
import moe.fuqiuluo.unidbg.session.SessionManager
import moe.fuqiuluo.utils.EMPTY_BYTE_ARRAY
import moe.fuqiuluo.utils.MD5
import java.nio.ByteBuffer

/** Lagrange.Core 2.1.3 DefaultAndroidBotSignProvider JSON POST contract. */
fun Routing.lagrange() {
    post("/energy") {
        val req = call.receive<LagrangeEnergyRequest>()
        req.checkProtocol()
        val uin = req.uin.jsonPrimitive.content.toLong()
        val guid = req.guid.lowercase()
        require(guid.isNotEmpty()) { "guid is required" }
        require(req.data.startsWith("810_") || req.data.startsWith("812_")) {
            "data must start with 810_ or 812_"
        }

        val session = lagrangeSession(uin, guid)
        val salt = lagrangeSalt(req, guid)
        val result = session.withLock {
            Dandelion.energy(session.vm, req.data, salt)
        }
        call.respond(APIResult(0, "success", result.toHexString().uppercase()))
    }

    post("/get_tlv553") {
        val req = call.receive<LagrangeTlv553Request>()
        req.checkProtocol()
        val uin = req.uin.jsonPrimitive.content.toLong()
        val guid = req.guid.lowercase()
        require(guid.isNotEmpty()) { "guid is required" }

        val session = lagrangeSession(uin, guid)
        val result = session.withLock {
            QSec.getXwDebugID(session.vm, uin.toString())
        }
        call.respond(APIResult(0, "success", result.value.toHexString().uppercase()))
    }
}

private fun lagrangeSession(uin: Long, guid: String): Session {
    return initSession(uin) ?: run {
        SessionManager.register(
            EnvData(
                uin = uin,
                androidId = "",
                guid = guid,
                qimei36 = "",
                qua = CONFIG.protocol.qua,
                version = CONFIG.protocol.version,
                code = CONFIG.protocol.code
            )
        )
        findSession(uin)
    }
}

private fun lagrangeSalt(req: LagrangeEnergyRequest, guid: String): ByteArray {
    val mode = when (req.data) {
        "810_d", "810_a", "810_f", "810_9" -> "v2"
        "810_2", "810_25", "810_7", "810_24" -> "v1"
        "812_a" -> "v3"
        "812_5" -> "v4"
        else -> error("cannot determine energy mode for ${req.data}")
    }
    val version = CONFIG.protocol.version
    val guidBytes = guid.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    val sub = req.data.substring(4).toInt(16)

    return when (mode) {
        "v1" -> ByteBuffer.allocate(8 + 2 + guidBytes.size + 2 + version.length + 4).apply {
            putLong(req.uin.jsonPrimitive.content.toLong())
            putShort(guidBytes.size.toShort())
            put(guidBytes)
            putShort(version.length.toShort())
            put(version.toByteArray())
            putInt(sub)
        }.array()

        "v2" -> ByteBuffer.allocate(4 + 2 + guidBytes.size + 2 + version.length + 4 + 4).apply {
            putInt(0)
            putShort(guidBytes.size.toShort())
            put(guidBytes)
            putShort(version.length.toShort())
            put(version.toByteArray())
            putInt(sub)
            putInt(0)
        }.array()

        "v3" -> {
            val phone = requireNotNull(req.phone) { "phone is required for 812_a" }.toByteArray()
            ByteBuffer.allocate(phone.size + 2 + 2 + version.length + 2).apply {
                put(phone)
                putShort(0)
                putShort(version.length.toShort())
                put(version.toByteArray())
                putShort(0)
            }.array()
        }

        "v4" -> {
            val receipt = requireNotNull(req.receipt) { "receipt is required for 812_5" }.toByteArray()
            val code = requireNotNull(req.code) { "code is required for 812_5" }
            val encrypt = Crypt().encrypt(receipt, MD5.toMD5Byte(code))
            ByteBuffer.allocate(receipt.size + 2 + encrypt.size).apply {
                put(receipt)
                putShort(encrypt.size.toShort())
                put(encrypt)
            }.array()
        }

        else -> EMPTY_BYTE_ARRAY
    }
}

private fun checkProtocol(version: String?, qua: String?) {
    require(version == null || version == CONFIG.protocol.version) {
        "version must match ${CONFIG.protocol.version}"
    }
    require(qua == null || qua == CONFIG.protocol.qua) {
        "qua must match ${CONFIG.protocol.qua}"
    }
}

@Serializable
private data class LagrangeEnergyRequest(
    val uin: JsonElement,
    val data: String,
    val guid: String,
    val ver: String? = null,
    val version: String? = null,
    val qua: String? = null,
    val phone: String? = null,
    val receipt: String? = null,
    val code: String? = null
) {
    fun checkProtocol() = checkProtocol(version, qua)
}

@Serializable
private data class LagrangeTlv553Request(
    val uin: JsonElement,
    val data: String,
    val guid: String,
    val version: String? = null,
    val qua: String? = null
) {
    fun checkProtocol() = checkProtocol(version, qua)
}
