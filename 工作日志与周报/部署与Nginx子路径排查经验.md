# CertAgent 部署与 Nginx 子路径排查经验

> 记录 CertAgent 在 Linux 服务器上的端口、Nginx 反向代理、前端 Vite 子路径、静态资源 MIME 和浏览器缓存问题。
> 适用项目：CertAgent；服务器：`10.18.87.51`；记录日期：2026-08-25。

## 1. 最终部署结构

```text
用户浏览器
  ├─ http://10.18.87.51/certagent/
  │    └─ 外层 Nginx :80
  │          └─ /certagent/ → 127.0.0.1:8123/
  │                ├─ 静态前端 dist/
  │                └─ /api/ → 127.0.0.1:8125
  └─ http://10.18.87.51:8123/
       └─ 内层 Nginx :8123
             ├─ 静态前端 dist/
             └─ /api/ → 127.0.0.1:8125
```

项目目录：

```text
/home/hisense/pro/Gitlab/CertAgent
```

端口约定：

| 端口 | 作用 | 访问方式 |
|---|---|---|
| 80 | 外层 Nginx，承载多个应用 | 用户正式入口 `/certagent/` |
| 8123 | CertAgent 内层 Nginx，前端静态文件 | 运维直连和排查入口 |
| 8125 | Uvicorn/FastAPI 后端 | 仅本机代理，不作为用户入口 |

正式推荐入口为：

```text
http://10.18.87.51/certagent/
```

## 2. 本次故障现象

### 2.1 登录失败

首页资源可以打开，但登录请求失败或返回 500。浏览器 Network 中看到：

```text
/api/v1/auth/login
```

实际应该是：

```text
/certagent/api/v1/auth/login
```

### 2.2 8123 直连白屏

访问：

```text
http://10.18.87.51:8123/
```

页面白屏，浏览器控制台提示：

```text
Failed to load module script
Expected a JavaScript module script but the server responded with MIME type text/html
```

这不是 JS 语法错误，而是浏览器请求 JS 文件时，服务器返回了 HTML。

### 2.3 现象中的关键判断

```text
/certagent/ 正常，:8123/ 异常
```

不代表后端端口异常。必须分别验证：

1. 首页 HTML 的 script 路径；
2. JS 文件是否真实存在；
3. JS 响应的 Content-Type；
4. API 是否通过正确路径到达 FastAPI。

## 3. 根因分析

### 3.1 Vite base 不会修改运行时 fetch

Vite 的 `base` 主要影响构建产物中的静态资源引用，例如：

```html
<script src="/certagent/assets/index.js"></script>
```

它不会自动修改源码里的运行时字符串：

```typescript
fetch('/api/v1/auth/login')
```

因此必须同时处理两类路径：

- 静态资源路径：由 Vite `base` 处理；
- API 请求路径：由统一 API 客户端生成。

### 3.2 页面中的裸路径会绕过统一 API 客户端

除了 `src/lib/api.ts`，下载函数等页面代码也可能直接写：

```typescript
fetch('/api/v1/jobs/...')
```

只修改 `api.ts` 不够，必须搜索全部前端源码：

```bash
grep -R -n --exclude-dir=node_modules --exclude-dir=dist "/api/v1" frontend/src
```

注释中的路径可以忽略，真正的 `fetch('/api/v1/...')` 必须全部消除。

### 3.3 固定 `/certagent/` 会影响 8123 直连

如果生产构建固定为：

```typescript
base: '/certagent/'
```

那么浏览器直接访问 8123 根路径时，也会请求：

```text
/certagent/assets/index.js
```

但内层 8123 通常只配置了 `/assets/`，没有配置 `/certagent/assets/`，于是 Nginx 的 SPA fallback 把这个请求返回成 `index.html`，最终产生 MIME 类型错误。

### 3.4 `text/html` 是定位 Nginx fallback 的重要信号

请求 JS 时如果响应为：

```text
Content-Type: text/html
```

优先检查：

1. JS 文件路径是否正确；
2. JS 文件是否存在；
3. Nginx `root` 是否指向当前 `dist`；
4. `try_files` 是否把不存在的资源回退到 `index.html`；
5. 浏览器是否缓存了旧入口 HTML。

不要先修改 React 或 FastAPI 业务代码。

## 4. 最终前端路径方案

为同时支持 `/certagent/` 和 `8123` 直连，生产构建使用相对路径：

```typescript
export default defineConfig(({ command }) => ({
  base: command === 'build' ? './' : '/',
}))
```

含义：

| 场景 | HTML 中的资源 | 浏览器实际解析 |
|---|---|---|
| 开发模式 | `/assets`、`/api` | 根路径，Vite proxy 转发 |
| `/certagent/` | `./assets`、`./api` | `/certagent/assets`、`/certagent/api` |
| `:8123/` | `./assets`、`./api` | `/assets`、`/api` |

API 客户端必须使用同一个 base：

```typescript
const BASE = `${import.meta.env.BASE_URL}api/v1`

export function apiUrl(path: string): string {
  return `${BASE}${path}`
}
```

页面中的下载、查询等请求也必须调用 `apiUrl()`，不能再次写死 `/api/v1`。

入口 HTML 中的 favicon 使用：

```html
<link rel="icon" type="image/svg+xml" href="%BASE_URL%favicon.svg" />
```

生产构建成功后的入口通常类似：

```html
<link rel="icon" type="image/svg+xml" href="./favicon.svg" />
<script type="module" crossorigin src="./assets/index-BQ4JtQZG.js"></script>
<link rel="stylesheet" crossorigin href="./assets/index-mTpcAuOD.css">
```

## 5. Nginx 配置原则

### 5.1 外层 80 端口

外层配置位于：

```text
/etc/nginx/sites-available/agents
```

核心配置：

```nginx
location = /certagent {
    return 301 /certagent/;
}

location /certagent/ {
    proxy_pass http://127.0.0.1:8123/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
}
```

`proxy_pass` 最后的 `/` 不能删除：

```nginx
proxy_pass http://127.0.0.1:8123/;
```

它负责把：

```text
/certagent/api/v1/auth/login
```

转发为内层接收的：

```text
/api/v1/auth/login
```

### 5.2 内层 8123 端口

内层配置位于：

```text
/etc/nginx/sites-available/certagent
```

推荐保持根路径部署：

```nginx
server {
    listen 8123;
    server_name 10.18.87.51;

    root /home/hisense/pro/Gitlab/CertAgent/frontend/dist;
    index index.html;
    client_max_body_size 50m;

    location /api/ {
        proxy_pass http://127.0.0.1:8125;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location /health {
        proxy_pass http://127.0.0.1:8125;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

不要在内层 8123 再添加 `/certagent/api/`，否则会和外层前缀剥离重复。

### 5.3 `server_name` 修改原则

`server_name` 只影响同一个监听端口的 Host 匹配：

- 8123 的 `server_name` 不影响 80 端口；
- 不能因为 8123 配了 IP，就直接修改 80 端口的 `server_name`；
- 修改 80 端口前，必须确认没有其他应用占用相同 IP/Host。

检查 80 端口实际配置：

```bash
sudo nginx -T | grep -nE 'listen .*80|server_name'
```

## 6. 标准验证流程

### 6.1 构建

```bash
cd /home/hisense/pro/Gitlab/CertAgent/frontend
npm run build
```

构建必须通过：

```text
✓ modules transformed
✓ built
```

### 6.2 检查入口 HTML

```bash
curl -s http://127.0.0.1:8123/ | \
grep -E 'script|stylesheet|favicon'
```

```bash
curl -s http://127.0.0.1/certagent/ | \
grep -E 'script|stylesheet|favicon'
```

两者都应返回相对资源路径，类似：

```text
./assets/index-xxx.js
./assets/index-xxx.css
./favicon.svg
```

### 6.3 检查静态资源 MIME

```bash
curl -I http://127.0.0.1:8123/assets/index-xxx.js
```

```bash
curl -I http://127.0.0.1/certagent/assets/index-xxx.js
```

预期：

```text
HTTP/1.1 200 OK
Content-Type: application/javascript
```

如果是 `text/html`，说明资源请求被 SPA fallback 接管，不能认为前端正常。

### 6.4 检查 API

直接访问内层：

```bash
curl -i -X POST \
  http://127.0.0.1:8123/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'
```

通过外层访问：

```bash
curl -i -X POST \
  http://127.0.0.1/certagent/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'
```

两者均应返回：

```text
HTTP/1.1 200 OK
```

### 6.5 检查真实 Host

```bash
curl -i -X POST \
  -H 'Host: 10.18.87.51' \
  http://127.0.0.1/certagent/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'
```

### 6.6 浏览器验证

正式入口：

```text
http://10.18.87.51/certagent/?v=20260825-1
```

8123 排查入口：

```text
http://10.18.87.51:8123/?v=20260825-1
```

浏览器中：

1. 打开 DevTools 的 Network；
2. 勾选 Disable cache；
3. 使用 Ctrl+Shift+R；
4. 确认 JS 请求返回 200；
5. 确认登录请求路径正确。

## 7. 常见错误与处理方式

| 现象 | 优先判断 | 处理 |
|---|---|---|
| 登录请求为 `/api/v1/...` | 前端源码或旧 bundle 写死根路径 | 统一使用 `apiUrl()`，重新 build |
| 登录请求为 `/certagent/api/v1/...` 但 404 | 外层/内层前缀处理重复或缺失 | 检查外层 `proxy_pass` 末尾 `/` |
| JS 返回 `text/html` | Nginx 找不到 JS，触发 SPA fallback | 检查入口路径、文件存在性、root 和缓存 |
| `/certagent/` 正常，8123 白屏 | 固定绝对 base 与直连入口冲突 | 使用 `base: './'` 或只保留一个正式入口 |
| 首页仍引用旧 hash | 浏览器或 Nginx 缓存旧 HTML | URL 增加版本参数，禁用缓存强刷 |
| CSS 200、JS 失败 | JS 路径或 MIME 单独错误 | 单独 `curl -I` 检查 JS |
| API 直连 200、浏览器失败 | 前端实际请求路径错误或浏览器缓存 | 检查 Network 的 Request URL |
| 修改 8123 后 80 端口异常 | 误改了共享 Nginx server block | 用 `nginx -T` 确认监听端口和 Host |

## 8. 不应采取的处理

1. 不要为了前端子路径修改 FastAPI 的 `/api/v1/*` 路由。
2. 不要同时在外层和内层都剥离 `/certagent`。
3. 不要删除外层 `proxy_pass` 末尾的 `/`。
4. 不要只检查 `frontend/src/lib/api.ts`，还要搜索所有 `fetch` 和下载函数。
5. 不要手工修改 `dist/assets/*.js`，应修改源码后重新构建。
6. 不要看到浏览器旧错误就立即判断服务器仍在运行旧代码，先检查实际 HTML、JS hash 和 HTTP 响应头。
7. 不要未经 `nginx -T` 检查就修改 80 端口 `server_name`，避免影响其他应用。
8. 不要把 `8123`、`8125`、Nginx `server_name`、Vite `base` 混为同一个概念。

## 9. 部署完成清单

- [ ] 前端源码所有 API 请求都使用统一 API 前缀；
- [ ] `npm run build` 成功；
- [ ] `dist/index.html` 资源路径符合当前部署方式；
- [ ] 8123 首页返回 200；
- [ ] `/certagent/` 首页返回 200；
- [ ] 8123 JS 返回 `application/javascript`；
- [ ] `/certagent/` JS 返回 `application/javascript`；
- [ ] 8123 登录接口返回 200；
- [ ] `/certagent` 登录接口返回 200；
- [ ] 浏览器 Network 使用最新 JS hash；
- [ ] 浏览器登录请求不是裸 `/api/v1`；
- [ ] Nginx 修改后执行过 `nginx -t`；
- [ ] `.env` 和 API Key 未上传；
- [ ] 本次变更已记录到 `项目/工作日志.md`。

## 10. 核心经验

1. **先分层定位，再修改代码**：HTML、静态资源、API、浏览器缓存分别验证。
2. **看到 MIME 为 HTML，优先查 Nginx fallback**：这通常不是 JS 本身的问题。
3. **子路径部署必须同时处理资源路径和 API 路径**：Vite `base` 不能替代 API URL 设计。
4. **统一 API 客户端是边界**：页面中不应出现第二套裸 `fetch('/api/...')`。
5. **相对 base 适合同时保留代理入口和直连入口**：`base: './'` 能让同一构建产物适配 `/certagent/` 与 `:8123/`。
6. **命令行验证优先于浏览器猜测**：`curl -I` 能快速区分真实服务器问题和浏览器缓存问题。
7. **Nginx 代理的斜杠有语义**：`proxy_pass` 是否带尾斜杠会改变上游收到的路径。
8. **生产部署必须保留可回滚点**：源码、构建 hash、Nginx 配置和验证结果都要记录。