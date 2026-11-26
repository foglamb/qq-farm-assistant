FROM gradle:8.14.4-jdk21 AS builder
WORKDIR /app
COPY . /app
RUN gradle clean shadowJar --no-daemon

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=builder /app/build/libs/unidbg-fetch-qsign-1.1.9-all.jar ./unidbg-fetch-qsign-all.jar
COPY --from=builder /app/txlib/9.2.20 ./txlib/9.2.20

EXPOSE 8081
ENTRYPOINT ["java", \
  "--add-opens=java.base/java.lang=ALL-UNNAMED", \
  "--add-opens=java.base/java.util=ALL-UNNAMED", \
  "--add-opens=java.base/java.nio=ALL-UNNAMED", \
  "--add-opens=java.base/sun.security.x509=ALL-UNNAMED", \
  "--add-opens=java.base/sun.nio.ch=ALL-UNNAMED", \
  "--add-exports=java.base/sun.security.x509=ALL-UNNAMED", \
  "-Djdk.attach.allowAttachSelf=true", \
  "-jar", "unidbg-fetch-qsign-all.jar"]
CMD ["--basePath=./txlib/9.2.20"]
