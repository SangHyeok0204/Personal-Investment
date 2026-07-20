# collector — ETF iNAV 수집/계산 서비스 (Phase-0 스캐폴드)
# 런타임 CA 베이크 (ADR-008): KIS/Naver/TWSE/KRX HTTPS가 사내 Somansa TLS 검사를
# 통과하려면 Somansa 루트 CA가 컨테이너 신뢰 저장소에 있어야 한다 (빌드타임만으론 부족).
FROM python:3.14-slim

ENV TZ=Asia/Seoul \
    PYTHONUNBUFFERED=1

# somansa-root.crt는 git에 커밋하지 않는다(.gitignore) — 빌드 전에
# C:\Users\user\.omc\assets\somansa-root.crt 를 이 디렉터리로 복사해 둘 것.
COPY somansa-root.crt /usr/local/share/ca-certificates/somansa-root.crt
RUN update-ca-certificates

# requests/pip/일반 ssl 모두 시스템 번들(표준 CA + Somansa)을 쓰게 고정.
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# 앱 코드는 깊은 경로에 둔다: verbatim 모듈들이 import 시 NEW_ROOT=parents[4]/[5]
# 를 계산하는데(구시스템의 S:\GE\raw\... 깊이 가정), /app 깊이에선 IndexError 가 난다.
# 이 값들은 기본 cache/db 경로에만 쓰이고(명시적 경로를 인자로 넘겨 미사용), 깊이만
# 충분하면 import 가 통과한다. 쓰기 가능한 캐시는 별도로 /app/.cache(볼륨) 를 쓴다.
WORKDIR /opt/inav/collector/root/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 구시스템 모듈 verbatim 이식분 (top-level 패키지 유지 — import 무변경 원칙)
COPY etf_inav/ ./etf_inav/
COPY kis_api/ ./kis_api/
COPY collector/ ./collector/

CMD ["python", "-m", "collector.main"]
