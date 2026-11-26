#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
WORK=${1:-"$ROOT/.build"}
UPSTREAM="$WORK/upstream"
APK="$WORK/qq-9.2.20.apk"
mkdir -p "$WORK"
if [ ! -d "$UPSTREAM/.git" ]; then
  git clone --filter=blob:none https://github.com/Linxiaoyaa/unidbg-fetch-qsign.git "$UPSTREAM"
fi
git -C "$UPSTREAM" checkout 58091e6c8134afb9c60878d29656db2bc17b9151
git -C "$UPSTREAM" checkout 58091e6c8134afb9c60878d29656db2bc17b9151^ -- libs/unidbg-android.jar
cp -a "$ROOT/patches/." "$UPSTREAM/"
if [ ! -f "$APK" ]; then
  curl -fL --retry 3 'https://android-apps.pp.cn/fs08/2025/09/29/7/110_269672f8c992b4e98001859c2322f2d5.apk?yingid=web_space&packageid=205963467&md5=f6d68c44bc64d089ac066eb56efdd662&minSDK=23&size=394895131' -o "$APK"
fi
APK_PATH="$APK" UPSTREAM_PATH="$UPSTREAM" python3 - <<'PY'
import hashlib,json,os,secrets,zipfile
from pathlib import Path
apk=Path(os.environ['APK_PATH']); upstream=Path(os.environ['UPSTREAM_PATH'])
data=apk.read_bytes()
assert len(data)==394895131
assert hashlib.md5(data).hexdigest()=='f6d68c44bc64d089ac066eb56efdd662'
assert hashlib.sha256(data).hexdigest()=='54930164077cd01ebc1677ac53c118ecf6dafdd646af2005edee41c3a4f9841d'
target=upstream/'txlib/9.2.20';target.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(apk) as z:(target/'libfekit.so').write_bytes(z.read('lib/arm64-v8a/libfekit.so'))
config=target/'config.json'
if not config.exists():
 config.write_text(json.dumps({'server':{'host':'0.0.0.0','port':8081},'key':secrets.token_hex(16),'auto_register':True,'protocol':{'package_name':'com.tencent.mobileqq','qua':'V1_AND_SQ_9.2.20_11650_YYB_D','version':'9.2.20','code':'11650'},'unidbg':{'dynarmic':False,'unicorn':True,'debug':False,'kvm':False,'is64Bit':True},'black_list':[]},indent=2)+'\n')
wrapper=upstream/'gradle/wrapper/gradle-wrapper.properties'
if wrapper.exists():
 text=wrapper.read_text().replace('https\\://services.gradle.org/distributions/','https\\://mirrors.cloud.tencent.com/gradle/')
 wrapper.write_text(text)
PY
cd "$UPSTREAM"
GRADLE_USER_HOME="$WORK/gradle-home" ./gradlew clean shadowJar --no-daemon
printf 'JAR=%s\n' "$UPSTREAM/build/libs/unidbg-fetch-qsign-1.1.9-all.jar"
printf 'CONFIG=%s\n' "$UPSTREAM/txlib/9.2.20/config.json"
