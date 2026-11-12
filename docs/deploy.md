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
| `deploy/Caddyfile` | HTTPS 인증서 자동 발급, 경로별 분기 |
| `frontend/Dockerfile.prod` | 프론트를 빌드해 Caddy 이미지에 넣는다 |
| `.env.prod.example` | 서버에서 `.env.prod`로 복사해 채운다 (커밋 금지) |

개발용과 다른 점:

- 외부에 열리는 포트는 **80·443뿐**이다. postgres·backend는 내부 네트워크에서만 보인다.
- backend는 `--reload` 없이, 소스 마운트 없이 이미지에 든 코드로 돈다 → 코드를 바꾸면 `--build`가 필요하다.
- redis는 띄우지 않는다. 단일 프로세스 구성은 `PRICE_CACHE_BACKEND=memory`라 쓰지 않는다.
- `VITE_API_BASE_URL`은 프론트 **빌드 시점**에 `https://${DOMAIN}`으로 박힌다. 주소를 바꾸면 `web`을 다시 빌드해야 한다.

## 2. 서버 준비 (처음 한 번)

### 2.1 인스턴스

- 셰이프 `VM.Standard.A1.Flex`(ARM), Ubuntu 24.04. 이 구성의 이미지는 전부 arm64를 지원한다.
- `E2.1.Micro`(메모리 1GB)는 부족하다. 프론트 빌드가 메모리 부족으로 실패하고, 백테스트 중 서버가 멈출 수 있다.
- 공인 IP는 **Reserved public IP**로 고정한다. 임시(ephemeral) IP는 인스턴스를 지우면 사라져 도메인이 끊긴다.

### 2.2 방화벽 — 두 군데 다 열어야 한다

1. **오라클 콘솔**: Networking → Virtual cloud networks → 해당 VCN → Security Lists → Default Security List → Add Ingress Rules
   - Source CIDR `0.0.0.0/0`, TCP, Destination port `80`
   - 같은 방법으로 `443` (TCP), `443` (UDP — HTTP/3, 선택)
2. **서버 안 iptables**: 오라클 Ubuntu 이미지는 22번 외에는 거부하는 규칙이 기본으로 들어 있다.

   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p udp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
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

IP가 바뀌면 sslip.io 주소도 바뀐다. 전시용 QR 코드에 넣을 주소는 IP를 고정한 뒤 정한다.

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

## 6. 주의

- **`.env.prod`의 `JWT_SECRET_KEY`를 바꾸면** 모든 사용자가 로그아웃된다. `POSTGRES_PASSWORD`는 DB를 처음 만들 때만 적용되므로, 만든 뒤에 바꾸면 backend가 DB에 못 붙는다.
- `caddy_data` 볼륨을 지우면 인증서를 다시 받는다. Let's Encrypt는 같은 이름의 재발급 횟수를 제한하므로 반복하지 않는다.
- 로그인·가입에는 아직 요청 횟수 제한이 없다. 공개 가입을 받는 동안에는 따로 막아야 한다.
