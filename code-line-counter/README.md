# 代码行数统计工具

一个只在本机读取文件的 React + Vite 代码规模统计工具。

## 使用方式

```powershell
cd code-line-counter
npm install

# 开发模式：分别启动前端和本地扫描服务
npm run dev
npm run server
```

开发页面地址为 `http://127.0.0.1:5174`。如果要让本地服务同时托管构建后的页面：

```powershell
npm run build
npm run start
```

然后打开 `http://127.0.0.1:8787`。

## 统计规则

- 只统计常见代码扩展名。
- 空行、纯注释行不计入有效代码行；包含代码的行计 1 行。
- 行尾注释不影响该行计数，字符串里的注释符号不会被当作注释。
- 自动忽略 `.git`、`node_modules`、`dist`、`build`、`target`、虚拟环境和缓存目录。
- 页面展示 1000 行公司规则作为参考；目录总量不会直接被判定为提交超限。
- 路径扫描服务仅绑定 `127.0.0.1`，不会上传代码内容。

## 测试

```powershell
npm test
```
