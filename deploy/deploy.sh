#!/bin/bash
# CertAgent 部署/更新脚本
# 首次部署: sudo bash deploy.sh
# 代码更新: sudo bash deploy.sh update
set -e

APP_DIR="/opt/certagent"
NGINX_CONF="/etc/nginx/sites-available/certagent"
SYSTEMD_UNIT="/etc/systemd/system/certagent.service"
SERVER_IP="10.18.87.51"

MODE="${1:-full}"  # full(首次完整部署) 或 update(仅更新代码重启)

echo "=== CertAgent 部署 [模式: $MODE] ==="

# ---------- update 模式：仅重建前端 + 重启后端 ----------
if [ "$MODE" = "update" ]; then
    echo ">>> 更新模式：重建前端 + 重启后端..."
    cd "$APP_DIR"
    
    # 激活虚拟环境，安装可能新增的依赖
    source venv/bin/activate
    pip install -r requirements.txt -q

    # 重新构建前端
    cd frontend
    npm install
    npm run build
    cd ..

    # 重启后端
    systemctl restart certagent
    
    echo ""
    echo "=== 更新完成 ==="
    echo "  访问地址: http://${SERVER_IP}"
    exit 0
fi

# ---------- full 模式：首次完整部署 ----------

# 1. 确保目录存在
if [ ! -d "$APP_DIR" ]; then
    echo "❌ 请先将项目文件上传到 $APP_DIR"
    echo "   示例: scp -r CertAgent/ user@${SERVER_IP}:/opt/certagent"
    exit 1
fi

cd "$APP_DIR"

# 2. 创建 Python 虚拟环境并安装依赖
echo ">>> 安装 Python 依赖..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. 构建前端
echo ">>> 构建前端..."
cd frontend
npm install
npm run build
cd ..

# 4. 创建 runs 目录（数据存储）
mkdir -p runs
chown -R www-data:www-data runs

# 5. 配置 systemd 服务
echo ">>> 配置后端服务..."
cp deploy/certagent.service "$SYSTEMD_UNIT"
systemctl daemon-reload
systemctl enable certagent
systemctl restart certagent

# 6. 配置 Nginx
echo ">>> 配置 Nginx..."
cp deploy/nginx.conf "$NGINX_CONF"

# 创建软链接到 sites-enabled
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/certagent

# 删除默认配置（避免冲突）
rm -f /etc/nginx/sites-enabled/default

# 测试配置是否正确
nginx -t

# 重载 Nginx
systemctl reload nginx

# 7. 开放防火墙 80 端口
if command -v ufw &> /dev/null; then
    ufw allow 80/tcp 2>/dev/null || true
elif command -v firewall-cmd &> /dev/null; then
    firewall-cmd --permanent --add-port=80/tcp 2>/dev/null || true
    firewall-cmd --reload 2>/dev/null || true
fi

# 8. 检查状态
echo ""
echo "=== 部署完成 ==="
echo ""
systemctl status certagent --no-pager -l | head -5
echo ""
echo "============================================"
echo "  访问地址: http://${SERVER_IP}"
echo "  默认账号: admin / admin"
echo "  API 文档: http://${SERVER_IP}/api/docs"
echo "============================================"
