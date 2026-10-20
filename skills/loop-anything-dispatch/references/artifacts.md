# 共享文件与可选飞书附件

通信介质和产物存放位置可以不同。Base 请求、成员目录和回复独立通过飞书云端传递，无需 NAS。文件只有在双方确实共享访问时才留在 NAS；共享情况未知或不可访问时，用飞书附件或对方可访问的云端链接，不交付发送方本地路径。

## 优先传共享路径

在请求 `context` 或回答 `result` 中附上路径及用途即可，字段按业务需要选择，例如：

```json
{"answer":"完整分析见文件，表格是逐项证据。","artifacts":[
  {"path":"/mnt/team/research/request-123/report.md","description":"完整分析"},
  {"path":"/mnt/team/research/request-123/evidence.csv","description":"逐项证据"}
]}
```

挂载路径不同则提供共享目录标识和相对路径，接收 Agent 按本机挂载读取。不要把发送方的本机临时路径当共享路径。结果文件使用请求专属位置，避免多个请求覆盖；保留到接收方取用完成。读取结果记录不表示引用的文件已经读完，平台不会删除 NAS 产物。

## 可选：飞书原生附件

对方不能访问 NAS，或用户需要云端副本时，复用已认证的 `lark-cli`，无需另写上传器。在文件所在目录执行上传；下载时在目标目录执行。CLI 使用当前目录内的相对文件路径：

```sh
lark-cli base +record-upload-attachment --base-token BASE_TOKEN --table-id TABLE_ID --record-id RECORD_ID --field-id FIELD_ID --file ./report.pdf
lark-cli docs +media-download --token FILE_TOKEN --output ./report.pdf
```

`FIELD_ID` 也可使用附件字段名称；`FILE_TOKEN` 取自记录附件字段的 `file_token`。在请求或结果里传附件位置、文件 token 和用途，接收方通过自己的飞书身份读取。业务产物放在业务记录中，避免与平台管理的通信版本混在一起。具体权限或命令差异沿用本机 lark-cli 的帮助和错误处理，不增加通信预检。

平台另有内联消息附件兜底：Base 消息超过 90000 个 UTF-16 单位时自动存为附件并完整读回。它不自动收集路径中的文件，不替代上述共享路径优先策略。
