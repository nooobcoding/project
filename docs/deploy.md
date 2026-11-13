# 운영 배포 (오라클 클라우드, 서버 한 대)

전시용으로 서버 한 대에 **단일 프로세스 구성**을 띄운다. 여러 프로세스 구성(`docker-compose.scale.yml`)은 쓰지 않는다 — 전시 규모는 단일 프로세스 한계(`docs-scale/docs-scale/08-capacity.md`) 안쪽이다.

## 1. 구성

```
인터넷 ──80/443──▶ web (Caddy) ──┬─ /api/*, /ws/*, /health, /docs ──▶ backend:8000 (uvicorn 1개)
                                 └─ 나머지 ──▶ 빌드된 프론트 정적 파일          │
                                                                           postgres (내부 전용)
```

| 파일 | 역할 |
|---|---|
| `docker-compose.prod.yml` | 운영 구성. 개발용 파일에 덧씌우지 않고 **단독으로** 쓴다 |
| `deploy/Caddyfile` | HTTPS 인증서 자동 발급, 경로별 분기, 로그인·가입 요청 횟수 제한 |
| `frontend/Dockerfile.prod` | 프론트를 빌드해 Caddy 이미지에 넣는다. Caddy는 요청 제한 플러그인을 넣어 다시 빌드한다 |
| `deploy/backup.sh` | DB 백업 (cron으로 하루 한 번) |
| `.env.prod.example` | 서버에서 `.env.prod`로 복사해 채운다 (커밋 금지) |

개발용과 다른 점:

- 외부에 열리는 포트는 **80·443뿐**이다. postgres·backend는 내부 네트워크에서만 보인다.
- backend는 `--reload` 없이, 소스 마운트 없이 이미지에 든 코드로 돈다 → 코드를 바꾸면 `--build`가 필요하다.
- redis는 띄우지 않는다. 단일 프로세스 구성은 `PRICE_CACHE_BACKEND=memory`라 쓰지 않는다.
- `VITE_API_BASE_URL`은 프론트 **빌드 시점**에 `https://${DOMAIN}`으로 박힌다. 주소를 바꾸면 `web`을 다시 빌드해야 한다.

### 1.1 요청 횟수 제한

앱에는 로그인·가입 횟수 제한이 없다. 공개 서버에서 비밀번호 대입과 가입 폭주를 막으려고 입구인 Caddy에서 IP 기준으로 막는다 (`caddy-ratelimit` 플러그인).

| 경로 | 한도 (IP당) |
|---|---|
| `/api/auth/login` | 1분에 30회 |
| `/api/auth/register` | 10분에 30회 |

- 전시장처럼 여러 사람이 한 공유기로 들어오면 바깥에서는 IP 하나로 보인다. 그래서 값을 넉넉히 잡았다. 전시 중에 관람객이 막히면 `deploy/Caddyfile`에서 `events`를 올리고 `web`을 재시작한다.
- 막힌 요청은 429와 `{"detail": "요청이 너무 많습니다. ..."}`를 받는다. 프론트(`api/client.ts`)는 본문이 JSON이 아니면 "서버와 연결할 수 없습니다"를 띄우므로 JSON으로 답해야 한다.
- 카운트는 Caddy 메모리에 있어서 `web`을 재시작하면 초기화된다.
- `rate_limit`의 실행 순서는 `before basic_auth`여야 한다. `before reverse_proxy`로 두면 `handle` 블록이 먼저 요청을 처리해서 제한이 한 번도 걸리지 않는다.

## 2. 서버 준비 (처음 한 번)

### 2.1 인스턴스

- 셰이프 `VM.Standard.A1.Flex`(ARM), Ubuntu 24.04. 이 구성의 이미지는 전부 arm64를 지원한다.
- `E2.1.Micro`(메모리 1GB)는 부족하다. 프론트 빌드가 메모리 부족으로 실패하고, 백테스트 중 서버가 멈출 수 있다.
- 공인 IP는 임시(ephemeral) IP를 그대로 쓴다. 재부팅하거나 정지했다 켜도 유지되고, **인스턴스를 지울 때만** 사라진다. Reserved IP는 무료 범위가 확실하지 않아 쓰지 않는다 — 이 서버의 원칙은 "요금 0원"이다.
- 인스턴스를 지울 때는 **부트 볼륨도 같이 삭제**하는 체크박스를 켠다. 남겨 두면 Block Storage → Boot Volumes에 쌓여 무료 한도(합계 200GB)를 잡아먹는다.

### 2.2 방화벽 — 두 군데 다 열어야 한다

1. **오라클 콘솔**: Networking → Virtual cloud networks → 해당 VCN → Security Lists → Default Security List → Add Ingress Rules
   - Source CIDR `0.0.0.0/0`, TCP, Destination port `80`
   - 같은 방법으로 `443` (TCP), `443` (UDP — HTTP/3, 선택)
2. **서버 안 iptables**: 오라클 Ubuntu 이미지는 22번 외에는 거부하는 `REJECT` 규칙이 기본으로 들어 있다. 새 규칙은 **REJECT보다 앞에** 넣어야 한다. 뒤에 넣으면 목록에는 보여도 효과가 없다. REJECT의 위치는 이미지마다 다르므로(2026-11 A1 Ubuntu 24.04에서는 5번) 번호를 먼저 찾는다.

   ```bash
   R=$(sudo iptables -L INPUT -n --line-numbers | awk '$2=="REJECT"{print $1; exit}')
   sudo iptables -I INPUT $R -m state --state NEW -p udp --dport 443 -j ACCEPT
   sudo iptables -I INPUT $R -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo iptables -I INPUT $R -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo netfilter-persistent save
   sudo iptables -L INPUT -n --line-numbers   # 80·443이 REJECT보다 위에 있는지 확인
   ```

### 2.3 도커 설치

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit    # 다시 접속해야 docker 그룹이 적용된다
```

## 3. 주소(DOMAIN) 정하기

Caddy는 `DOMAIN` 이름으로 Let's Encrypt 인증서를 받는다. 발급하려면 **그 이름이 서버 공인 IP를 가리키고 80번 포트가 열려 있어야** 한다.

| 방법 | 주소 예 | 비용 | 준비 |
|---|---|---|---|
| sslip.io | `129-225-161-79.sslip.io` | 무료 | 없음 — IP를 `-`로 이은 이름이 그 IP를 가리킨다 |
| DuckDNS | `myname.duckdns.org` | 무료 | duckdns.org에서 이름을 만들고 IP 입력 |
| 도메인 구매 | `myname.com` | 연 1~2만 원 | 등록 업체에서 A 레코드를 공인 IP로 |

IP가 바뀌면 sslip.io 주소도 바뀐다. 인스턴스를 다시 만들 일이 없다는 확신이 선 뒤에 전시용 QR 코드 주소를 정한다.

방화벽(2.2의 두 곳)이 열리기 전에 `web`을 띄우면 인증서 발급이 계속 실패한다. Let's Encrypt는 실패가 반복되면 한동안 발급을 막으므로, 방화벽을 먼저 연다.

## 4. 배포 (처음)

```bash
git clone https://github.com/nooobcoding/project.git coin && cd coin
git checkout <배포할 브랜치>

cp .env.prod.example .env.prod
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env.prod
sed -i "s/^JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$(openssl rand -hex 32)/" .env.prod
nano .env.prod    # DOMAIN만 직접 고친다

docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

- 첫 빌드는 몇 분 걸린다(프론트 빌드, 파이썬 패키지 설치).
- 마이그레이션은 backend가 뜰 때 자동으로 돈다(`docker-entrypoint.sh`).
- 코인 목록은 기동 직후 Upbit에서 채운다. 시세는 그 뒤부터 들어온다.

확인:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
curl https://<DOMAIN>/health          # {"status":"ok"}
```

관리자 지정 (먼저 웹에서 가입한 뒤):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend python scripts/set_admin.py <이메일>
```

## 5. 운영

명령이 길어서 별칭을 걸어 두면 편하다:

```bash
echo 'alias dcp="docker compose -f docker-compose.prod.yml --env-file .env.prod"' >> ~/.bashrc && source ~/.bashrc
```

| 할 일 | 명령 |
|---|---|
| 코드 갱신 | `git pull && dcp up -d --build` |
| 로그 | `dcp logs -f backend` (`web`, `postgres`도 같다) |
| 재시작 | `dcp restart backend` |
| 정지 | `dcp down` — **`-v`를 붙이면 DB와 인증서가 지워진다** |

- 모든 서비스가 `restart: unless-stopped`라 서버를 재부팅해도 다시 뜬다.
- 로그는 서비스마다 10MB × 3개까지만 남는다.

### 5.1 백업과 복구

`deploy/backup.sh`가 `pg_dump`를 압축해 `~/backups`에 남기고, 7일이 지난 파일은 지운다. 설치는 한 번만 하면 된다:

```bash
mkdir -p ~/backups
(crontab -l 2>/dev/null; echo '0 4 * * * /home/ubuntu/coin/deploy/backup.sh >> /home/ubuntu/backups/backup.log 2>&1') | crontab -
```

- 서버 시간대는 UTC라 `0 4`는 한국 시간 13시다.
- 같은 서버 디스크에 남기므로, 서버 자체를 잃으면 백업도 같이 잃는다. 전시 직전에는 내 PC로 내려받아 둔다:
  `scp -i <키> ubuntu@<IP>:backups/<파일> .`
- 덤프가 실패하면 파일을 남기지 않고 종료 코드 1로 끝난다(`pipefail`). 이 옵션이 없으면 실패해도 빈 파일이 정상 백업처럼 남는다.

복구할 때는 backend를 멈추고, 빈 DB에 붓는다:

```bash
dcp stop backend
dcp exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
gzip -dc ~/backups/<파일>.sql.gz | dcp exec -T postgres sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
dcp start backend
```

## 6. 주의

- **`.env.prod`의 `JWT_SECRET_KEY`를 바꾸면** 모든 사용자가 로그아웃된다. `POSTGRES_PASSWORD`는 DB를 처음 만들 때만 적용되므로, 만든 뒤에 바꾸면 backend가 DB에 못 붙는다.
- `caddy_data` 볼륨을 지우면 인증서를 다시 받는다. Let's Encrypt는 같은 이름의 재발급 횟수를 제한하므로 반복하지 않는다.
