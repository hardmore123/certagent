# CertAgent 服务器部署指南

## 架构

```
浏览器(同事电脑) → Nginx(:8123) ─┬─ /           → 前端静态文件(dist/)
                                 ├─ /api/*      → Uvicorn(:8125)
                                 └─ /health     → Uvicorn(:8125)
```

## 前置条件

| 项目 | 要求 |
|------|------|
| 操作系统 | Ubuntu 20.04+ / CentOS 7+ |
| Python | >= 3.11 |
| Node.js | >= 18 |
| Nginx | 已安装 |
| LibreOffice | 需要处理 .doc 文件时安装 |

## 快速部署

```bash
# 1. 上传项目到服务器
scp -r CertAgent/ user@your-server:/opt/certagent

# 2. SSH 登录服务器
ssh user@your-server

# 3. 一键部署
cd /opt/certagent
sudo bash deploy/deploy.sh
```

## 手动部署步骤

### Step 1: 安装系统依赖

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip nginx

# Node.js (通过 NodeSource)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# LibreOffice (处理 .doc 文件)
sudo apt install -y libreoffice
```

### Step 2: 后端

```bash
cd /opt/certagent
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填写 LLM 配置
```

### Step 3: 前端构建

```bash
cd /opt/certagent/frontend
npm install
npm run build
# 产物: frontend/dist/
```

### Step 4: 配置 Nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/certagent
sudo ln -sf /etc/nginx/sites-available/certagent /etc/nginx/sites-enabled/certagent
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### Step 5: 配置后端服务

```bash
sudo cp deploy/certagent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable certagent
sudo systemctl start certagent
```

## 验证

```bash
# 检查后端
curl http://localhost:8125/health

# 检查 Nginx
curl http://localhost:8123/health

# 查看后端日志
journalctl -u certagent -f
```

## 同事访问

服务器 IP 为 `10.18.87.51`，同事直接浏览器访问：

```
http://10.18.87.51
```

默认账号：`admin` / `admin`

## 防火墙

如果服务器有防火墙，需放行 80 端口：

```bash
# Ubuntu (ufw)
sudo ufw allow 80/tcp

# CentOS (firewalld)
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --reload
```

## 更新部署

```bash
cd /opt/certagent

# 拉取最新代码（如果用 git）
git pull

# 重新构建前端
cd frontend && npm run build && cd ..

# 重启后端
sudo systemctl restart certagent
```

## 常见问题

### Q: 上传文件报 413 错误
A: nginx.conf 中 `client_max_body_size` 已设为 50m，如果文件更大可调大。

### Q: 后端超时
A: nginx.conf 中 `proxy_read_timeout` 已设为 300s，解析大文件可再调大。

### Q: 服务器是 Windows
A: 不使用 systemd，改用 NSSM 注册为 Windows 服务，Nginx 用 Windows 版。详见下方说明。

---

## Windows 服务器部署（备选）

如果服务器也是 Windows：

1. 安装 Python 3.11+、Node.js 18+、Nginx for Windows
2. 后端启动：
   ```cmd
   cd C:\certagent
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python -m webapi
   ```
3. 前端构建：
   ```cmd
   cd frontend
   npm install
   npm run build
   ```
4. Nginx 配置同 Linux 版，路径改为 Windows 格式：
   ```nginx
   root C:/certagent/frontend/dist;
   ```
5. 用 NSSM 将后端注册为 Windows 服务：
   ```cmd
   nssm install CertAgent "C:\certagent\venv\Scripts\python.exe" "-m" "uvicorn" "webapi.app:app" "--host" "127.0.0.1" "--port" "8000"
   nssm start CertAgent
   ```
