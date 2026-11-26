FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY PadLogin.csproj ./
RUN dotnet restore PadLogin.csproj
COPY . .
RUN dotnet publish PadLogin.csproj -c Release -o /out --no-restore

FROM mcr.microsoft.com/dotnet/runtime:8.0
WORKDIR /app
COPY --from=build /out ./
ENV PORT=8080 PAD_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8080
ENTRYPOINT ["dotnet", "PadLogin.dll"]
