# claim_bot

这是一个用于演示的 Windows 桌面工具（基于 PySimpleGUI + requests），用于按指定时间/间隔向指定网页发起请求以尝试抢领活动道具。

主要功能
- 可配置 URL、Method、Headers、Form key=value 或 Raw Body
- 可设置定时开始时间和每次请求的间隔（秒）
- 支持重试次数（0 = 无限）、成功关键词检测、代理
- 支持保存/加载配置、导出日志

使用方法
1. 打开 Windows/命令行，确保已安装 Python 3.8+
2. 安装依赖：
   pip install -r requirements.txt
3. 运行程序：
   python claim_bot.py

打包为 exe（GitHub Actions 已包含自动构建 workflow）
- 本仓库包含一个 GitHub Actions workflow，会在 Windows runner 上使用 PyInstaller 构建 single-file exe，并创建 Release 上传 exe 资产。

注意与免责声明
- 本工具为技术演示，请确保你的使用符合目标网站的服务条款与法律法规。
- 许多活动页面有登录、CSRF、验证码、JS 签名等防护，单纯的请求可能无法成功。若目标页面有复杂防护，请使用浏览器自动化（Playwright/Selenium）并结合登录态。
