# 涂鸦智能 Home Assistant 自定义集成 (新风系统增强版)

基于官方 Home Assistant `tuya` 核心集成定制优化，专为解决涂鸦新风机（`xfj` / `kj` 类别）在 Home Assistant 中温湿度显示异常、风速档位不正确、模式单一等痛点问题。

通过本仓库，可在 HACS 中作为自定义存储库添加并一键安装，**无缝覆盖 Home Assistant 内置同名 `tuya` 官方集成**，原有配置和已添加的所有涂鸦设备保持不变，即装即用。

---

## 🌟 核心修复与改进

### 1. 温度与湿度读数修复
- **10倍数值缩放修正**：涂鸦新风设备常将温度、湿度作为 10 倍整数上报（例如 `255` 代表 `25.5°C`，`550` 代表 `55.0%`），但云端 Schema 缺失 `scale` 属性导致 HA 显示为数百度。本集成自动智能识别并还原真实温湿度读数。
- **单位与实体类型保护**：修复涂鸦云端返回单位缺失导致 HA 丢弃 `device_class` 和实体单位的问题，强制补齐 `°C` 和 `%`。
- **状态回退兜底**：若上报值缺失，自动回退到 `device.status`，确保数据始终在线。

### 2. 1-6 档风速原生支持
- **告别 0-100% 连续滑动条**：新风机设备（`xfj`）原生配置 6 档离散风速（1 档至 6 档）。
- **精准档位映射**：解决官方集成百分比计算偏差导致 1 档无法选中的缺陷，风扇卡片中可直接选择 1 ~ 6 档风速。
- **指令直接下发**：风速设置绕过云端转换层阻碍，直达设备 MCU。

### 3. 多元化新风工作模式
- **全模式覆盖**：不再仅有单一的 `manual`（手动）模式，原生支持：
  - **自动 (auto)**
  - **净化 / 内循环 (purify / indoor_loop)**
  - **通风 / 外循环 (ventilation / outdoor_loop)**
  - **睡眠 (sleep)**
  - **手动 (manual)**
- **循环风门智能联动**：联动 `loop_mode` 与 `switch_ventilate`，无论新风机采用哪种 DPCode 协议，均能准确切换内循环与外循环通风。
- **直发 DP 指令**：绕过官方 `EnumTypeInformation` 的严格白名单校验，彻底避免控制模式时抛出 `PrepareSetValueError` 异常。

### 4. 丰富的新风传感器与开关控制
- **全套环境传感器**：新增并完善了 `temp_indoor`（室内温度）、`humidity_indoor`（室内湿度）、`pm25`、`co2_value`、`tvoc`、`ch2o_value`（甲醛）、`filter_life`（滤网寿命）等。
- **快捷开关与选择器**：支持负离子（`anion`）、童锁（`child_lock`）、通风开关（`switch_ventilate`）、循环模式（`loop_mode`）、滤网复位（`filter_reset`）等。
- **原生中文本地化**：附带完整的 `zh-Hans.json` 简体中文翻译。

---

## 🚀 安装方法 (HACS 覆盖安装)

### 前提条件
已在 Home Assistant 中安装了 [HACS](https://hacs.xyz/)。

### 安装步骤
1. 打开 Home Assistant，点击左侧菜单栏的 **HACS**。
2. 点击右上角的三个点（**⋮**），选择 **自定义存储库 (Custom repositories)**。
3. 在 **存储库 (Repository)** 栏输入本仓库地址：
   ```text
   https://github.com/your-username/ha-tuya
   ```
   > 注：请将上面的地址替换为您在 GitHub 上创建的仓库地址。
4. **类别 (Category)** 选择 **集成 (Integration)**，点击 **添加 (Add)**。
5. 在 HACS 集成列表中找到 **Tuya**，点击右下角 **下载 (Download)**。
6. 下载完成后，**重启 Home Assistant** 容器或主机。

---

## 🔍 验证生效

重启 Home Assistant 后，进入 **设置** -> **系统** -> **日志**。
您可以在日志中看到类似如下提示：
```text
WARNING (MainThread) [homeassistant.loader] We found a custom integration tuya which has already been defined by Home Assistant - it will take precedence over the core integration.
```
这表明自定义 Tuya 集成已成功接管并覆盖官方内置的 Tuya 集成！

所有已添加的涂鸦设备均会自动无缝迁移至本集成，您的新风机实体将立即获得完整的 1-6 档风速、多工作模式及正确的温湿度数据。

---

## 📄 许可说明
本项目遵循与官方 Home Assistant 核心集成相同的开源许可协议。
