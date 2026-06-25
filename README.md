# Gemini 水印去除工具

使用反向 Alpha 混合算法处理 Gemini AI 图片星形水印的本地桌面工具。程序不再只依赖固定位置：会先校验默认位置和已记录位置；未匹配时使用 OpenCV 在图片中寻找候选位置，由用户确认后去除并记住新位置。

网页端建议使用 Voyager：[https://github.com/Nagi-ovo/gemini-voyager](https://github.com/Nagi-ovo/gemini-voyager)

参考项目：[https://github.com/GargantuaX/gemini-watermark-remover](https://github.com/GargantuaX/gemini-watermark-remover)

## 使用方法

### 直接运行 Python 脚本

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

运行程序：

```powershell
python main.py
```

要求 Python 3.10 或更高版本。

### 打包成 EXE

安装打包依赖：

```powershell
python -m pip install -r requirements.txt
```

使用 PyInstaller 打包：

```powershell
pyinstaller --noconfirm --clean --windowed --name GeminiWatermarkRemover --icon assets\app.ico --add-data "assets;assets" --collect-binaries cv2 --workpath build\pyinstaller --distpath release --specpath build\pyinstaller main.py
```


## 功能

- 单个文件处理与文件夹批量处理。
- 固定规则优先：先校验默认位置和已记录位置。
- 自动候选定位：仅识别 48px、96px 原始模板，并要求匹配分数不低于 0.50 且通过水印校验。
- 用户确认新位置后写入 `data/config.json`，后续图片可直接复用。
- 设置页支持跟随系统、浅色、深色三种窗口显示模式。
- 主窗口可缩放；设置页内容过长时可滚动查看。
- 单图预览支持滚轮缩放、左键拖拽，双击图片或关闭窗口即可退出查看器。

## 使用位置规则

1. 选择图片并点击“去除水印”。
2. 程序先校验右下角默认位置和已确认位置。
3. 未匹配时，确认窗口显示候选位置；在水印附近点击即可重新定位。
4. 只能选择 `48` 或 `96` 原始模板，不支持任意缩放尺寸。
5. 点击“确认并记住位置”，规则将写入 `data/config.json`。

批处理不会弹出确认窗口，仅处理默认位置或已记录位置能够校验通过的文件；失败项会显示原因。

## 项目结构

```text
Gemini_watermark_remove/
├── assets/                         # 图标与 48/96 水印模板
├── gemini_watermark_remover/       # 源码
│   ├── app.py                      # 主界面、单图与批处理
│   ├── config.py                   # 设置与位置规则
│   ├── dialogs.py                  # 大图预览与确认弹窗
│   ├── paths.py                    # 资源、数据目录和 DPI 初始化
│   ├── theme.py                    # 深浅色主题与系统主题读取
│   └── watermark.py                # OpenCV 定位和 Alpha 去除算法
├── tests/                          # 自动化测试
├── .github/workflows/tests.yml     # GitHub Actions
├── main.py                         # 程序入口
├── requirements.txt                # 依赖列表
└── README.md                       # 使用说明
```

运行时数据仅在程序同级 `data/` 目录生成：

```text
data/
├── config.json          # 设置和已确认的位置
└── YYYYMMDD_HHMMSS/     # 默认批处理输出
```
