# AutoSweeper

这是一个面向经典 Windows 扫雷界面的自动求解脚本。启动后会让你像截图工具一样拖拽框选扫雷窗口或包含棋盘的大区域，脚本会自动定位核心格子区域，然后按给定行列数截图识别棋盘，优先执行可证明零风险的扫雷推理，并用鼠标左键开安全格、右键标雷。

## 环境配置

1. 安装 Python 3.10 或更新版本。Windows 上推荐从 <https://www.python.org/downloads/windows/> 安装，并勾选 `Add python.exe to PATH`。
2. 在本目录打开 PowerShell：

```powershell
cd D:\User\桌面\AutoSweeper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

如果安装了 Python Launcher，也可以把第一条换成 `py -3 -m venv .venv`。

如果 PowerShell 禁止激活虚拟环境，可以先执行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 运行方式

如果使用 `sweeper` conda 环境，可以把下面命令里的 `python` 换成：

```powershell
D:\miniconda3\envs\sweeper\python.exe
```

基础难度，9x9，10 雷：

```powershell
python .\autosweeper.py --preset basic
```

中级难度，16x16，40 雷：

```powershell
python .\autosweeper.py --preset medium
```

专家难度，16x30，99 雷：

```powershell
python .\autosweeper.py --preset hard
```

兼容别名也可以用：`beginner/easy`、`intermediate`、`expert`。

自定义棋盘：

```powershell
python .\autosweeper.py --rows 20 --cols 30 --mines 120
```

程序启动后，拖拽框选扫雷窗口或包含棋盘的大区域即可，不需要严格贴着格子边缘。脚本会在框选截图里自动寻找 `rows x cols` 的核心格子区域，再按行列数切格识别。

如果自动定位误判，可以关闭自动裁剪，退回“严格使用框选区域”的旧模式：

```powershell
python .\autosweeper.py --preset expert --no-auto-crop
```

也可以调高定位阈值，让脚本更保守：

```powershell
python .\autosweeper.py --preset expert --crop-min-score 0.6
```

如果识别到的是全新棋盘，也就是所有格子都未打开、没有旗子，脚本会先自动点击第一下。默认点棋盘中心附近：

```powershell
python .\autosweeper.py --preset expert --first-click center
```

也可以改成角落、随机或关闭自动第一下：

```powershell
python .\autosweeper.py --preset expert --first-click corner
python .\autosweeper.py --preset expert --first-click random
python .\autosweeper.py --preset expert --first-click none
```

## 建议先校准识别

先只识别不点击：

```powershell
python .\autosweeper.py --preset expert --once
```

识别输出里：

- `#` 表示未开格；
- `F` 表示旗子；
- `.` 表示空白开格；
- `1` 到 `8` 表示数字。

如果输出棋盘和屏幕不一致，通常是自动定位区域不准、行列数填错，或当前扫雷皮肤和经典灰色格差异较大。可以先扩大框选到整个窗口重试；仍不准时用 `--no-auto-crop` 精确框选核心棋盘。

## 安全运行选项

默认只推理零风险步骤，不猜。下面这条就是推荐运行方式：

```powershell
python .\autosweeper.py --preset expert
```

如果你明确接受风险，可以允许无零风险步时按最低估计雷率猜测：

```powershell
python .\autosweeper.py --preset expert --guess
```

打印计划但不实际点击：

```powershell
python .\autosweeper.py --preset expert --dry-run --print-board
```

如果框选后看起来没有动作，先观察终端输出：

- 出现 `正在截图并定位核心棋盘区域...`：自动定位可能需要几秒。
- 出现 `全新棋盘，先开局点击 ... 屏幕坐标=(x, y)`：脚本已经发出第一下点击。如果游戏没反应，可能是扫雷窗口以管理员权限运行，终端也需要用管理员权限启动。
- 如果识别棋盘全是 `#` 但没有点击，确认没有加 `--once` 或 `--first-click none`。

框选遮罩刚消失时如果截图还没恢复，可以加长等待：

```powershell
python .\autosweeper.py --preset expert --after-select-delay 0.8
```

## 算法说明

脚本会把所有已打开数字格转换成约束，例如“这 5 个相邻未知格中恰有 2 个雷”。求解优先级如下：

1. 确定性闭包：基础规则、子集差分、交集上下界和总雷数约束，能证明安全/必雷就立刻执行。
2. 精确枚举：确定性闭包没有动作时，把边界未知格拆成互不相关的连通分量，对每个分量枚举所有满足约束的布雷方案，只执行在所有合法方案中都确定的格子。
3. 概率猜测：默认关闭；只有加 `--guess` 才会在没有零风险动作时选择估计雷率最低的格子。

- 某格在所有方案中都不是雷：左键打开；
- 某格在所有方案中都是雷：右键标旗；
- 如果没有零风险操作且没有加 `--guess`，脚本会停止。
- 全新棋盘的第一下是单独的开局策略，由 `--first-click` 控制，不算中盘概率猜测。

提供 `--mines` 或使用预设时，脚本还会把“总雷数”加入全局约束，因此能处理非边界未知格的概率和部分只靠总雷数才能推出的确定结论。

## 注意事项

- 目前识别器针对 `fig.png` 这类经典灰色立体格扫雷皮肤调校。若使用现代主题、缩放滤镜或非标准颜色，可能需要微调 `autosweeper.py` 里的 `ClassicRecognizer` 阈值。
- 自动扫雷无法保证每局必胜；当局面本身需要猜测时，默认会停住，只有 `--guess` 会让脚本冒险。
- 鼠标会被脚本控制。需要中止时，在终端按 `Ctrl+C`。
