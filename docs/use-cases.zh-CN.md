# 使用场景手册

[English](use-cases.md) · [简体中文](use-cases.zh-CN.md) · [返回 README](../README.zh-CN.md)

当一个大型项目里存在一块很适合交给 DeepSeek 的独立环节时，使用这份手册。Codex 继续作为当前任务的总控，只委派边界明确的阶段；读回并评估结果后，再推进整个项目。

## 委派前先做五个判断

1. **最小可用工作流是什么？** 只处理文案、只复核 treatment、只改一个代码模块，或只做一次独立审查。
2. **哪个目录包含全部必要输入？** 优先使用专用工作流目录，不要直接给整个项目根目录。
3. **DeepSeek 是否需要修改项目文件？** 如果不需要，使用 `proposal-only`。
4. **产物是文字还是媒体？** 本 Skill 处理文字和代码；媒体渲染、导出、上传、发布应使用其它已授权工具。
5. **能否接受 Harness 的部署级默认模型变化？** RC.6 新建会话时会把所选模型持久化为 deployment default。

## 1. 复杂 Campaign 中的独立文案环节

### 适合处理

- Campaign 方向、标题、产品文案、VO、SUPER 和 CTA 方案
- 按已提供的品牌语气做调整
- 把一个已批准的信息改写成不同渠道版本
- 从第二视角检查清晰度、信息层级和“是否太抽象”

### 推荐路由

| 决策 | 默认值 |
| --- | --- |
| Preset | `standard` |
| Model | 细腻文案用 `deepseek-v4-pro`；低风险快速迭代可用 `deepseek-v4-flash` |
| Scope | 只出候选用 `proposal-only`；确需改文件时用专用 `single-dir` |
| Directory | 使用 `/absolute/project/workstreams/copy`，而不是项目根目录 |

### 对 Codex 这样说

```text
使用 $delegate-to-deepseek-harness，处理
/absolute/project/workstreams/copy 里的文案环节。
阅读 brief.md 和 brand-voice.md，给出三个 campaign 方向；
每个方向包含一句 proposition、三个标题、一段 30 字 VO 和一个 CTA。
所有已提供口径保持不变。只出方案，不修改项目文件；
完成后把结果与状态读回当前任务。
```

### 验收检查

- 每一项宣传口径都能追溯到已提供 brief。
- 三个方向确实不同，而不是同义词替换。
- 语气、字数和格式要求都满足。
- `STATUS.json.status` 为 `done`，completion reason 为 `completed`。

## 2. 视频前期的文字环节

### 适合委派的阶段

- Treatment 结构与故事节拍
- 脚本、VO、SUPER、lower-third、title card 文案
- 镜头文字清晰度与连贯性复核
- 字幕或转录稿清理、分段
- 图片/视频生成提示词预检
- 识别缺少证据的产品口径和缺失素材

### 不要把这些写成“已经完成视频工作”

- 图片或视频渲染
- 时间线剪辑或媒体 conform
- 调色、混音、VFX、最终导出
- 上传、客户交付、发布或平台提交
- 没有原始证据时的版权确认或口径核验

### 推荐路由

| 决策 | 默认值 |
| --- | --- |
| Preset | `standard` |
| Model | `deepseek-v4-pro` |
| Scope | 复核用 `proposal-only`；确需生成可编辑文字文件时用专用 `single-dir` |
| Directory | treatment、脚本、转录稿或提示词专用目录 |

### 对 Codex 这样说

```text
使用 $delegate-to-deepseek-harness，处理
/absolute/project/video-treatment 中纯文字的视频前期环节。
复核 60 秒故事节拍、VO、SUPER 和镜头文字，返回：
1）连贯性问题；2）更紧凑的节拍顺序；3）修改后的文字；
4）需要证据支撑的口径。不要渲染、剪辑、导出、上传或发布媒体。
只出方案。最后读回 RESULT.md、可能存在的 OPINION.md 和最终状态。
```

### 验收检查

- 故事调整保留已提供事实、时长、格式和必选节点。
- `VO`、`SUPER`、UI 文案与画面说明保持分栏，不互相混淆。
- 不虚构素材、产品功能、数字或客户批准状态。
- 结果明确标注为文字前期，不冒充成片。

## 3. 快速改写或资料归纳

对可撤销、低风险且更看重速度的任务，可用 `deepseek-v4-flash`：转录摘要、文案压缩、结构化提取或格式统一。

```text
使用 $delegate-to-deepseek-harness 和 DeepSeek V4 Flash，
把 /absolute/project/research/interviews 中的访谈记录整理成精简主题矩阵。
只出方案；引用原文保持不变，证据与推断分开，并把结果读回。
本轮可以接受 Harness 的部署级默认模型改为 Flash。
```

如果任务包含高风险宣传口径、复杂跨文件依赖或细腻品牌语气，不要只为追求速度选择 Flash。

## 4. 聚焦的代码实现

### 推荐路由

| 决策 | 默认值 |
| --- | --- |
| Preset | `code` |
| Model | `deepseek-v4-pro` |
| Scope | 只有确实需要多个文件时才用 `cross-file` |
| Directory | 同时包含目标修改和测试的最小仓库或 package 根目录 |

### 对 Codex 这样说

```text
使用 $delegate-to-deepseek-harness，在
/absolute/project/packages/parser 中实现边界清楚的 parser 修复。
使用 code preset 和 cross-file scope。先读本地贡献规则；
只修改 parser 行为及其回归测试，运行最小相关测试，报告修改文件和验证结果。
不要 commit、push、发布或触碰其它 package。
```

### 验收检查

- Diff 没有超出指定 package 和任务范围。
- 回归测试能证明行为变化。
- 报告实际命令、退出码和未覆盖项。
- Codex 在宣布完成前独立检查 diff。

## 5. 不改文件的独立审查

想得到 DeepSeek 的分析、但所有修改仍由 Codex 控制时，使用 `proposal-only`。

```text
使用 $delegate-to-deepseek-harness，审查 /absolute/project
当前方案可能出现的失败模式。不要修改项目文件。
在 RESULT.md 中按优先级列出 finding、文件位置和修复建议；
可选战略意见写入 OPINION.md；需要扩权时写 ASK.md。
把全部内容读回，并在当前 Codex 任务中评估。
```

它适合架构意见、文案审查、安全模型质疑、交付预检和替代方案。DeepSeek 结果属于辅助证据，不自动等于批准。

## 6. 继续同一个 Harness 会话

如果追问依赖刚才会话的上下文，在完成一次委派后继续同一 session：

```sh
python3 scripts/dsh_harness.py send SESSION_ID \
  --text-file /absolute/path/to/follow-up.txt \
  --timeout 900
```

当工作目录、授权、任务类型或写入范围发生实质变化时，创建新的委派任务。

## 直接使用 CLI

通常由 Codex 代为调用客户端。手动使用时，把较长任务保存在 UTF-8 文件中，而且不要与 `delegate` 会覆盖的控制文件同名：

```sh
python3 scripts/dsh_harness.py delegate \
  --cwd /absolute/project/workstreams/copy \
  --preset standard \
  --model deepseek-v4-pro \
  --scope proposal-only \
  --title "Campaign copy review" \
  --text-file /absolute/project/briefs/delegate-copy.txt \
  --timeout 900

python3 scripts/dsh_harness.py read-back \
  --cwd /absolute/project/workstreams/copy

python3 scripts/dsh_harness.py status \
  --cwd /absolute/project/workstreams/copy
```

不要把 API key、密码、私钥、session cookie 或无关客户资料写入任务文件。
