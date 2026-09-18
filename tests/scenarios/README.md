# 模拟场景验收

研究与差旅 Loop 的可复用定义位于 [`loop_anything/examples/`](../../loop_anything/examples/)，通过平台公开协议构建，Engine 没有示例专用的业务分支。

```sh
python3 -m loop_anything serve --demo --open
```

这会注册示例，不自动创建运行。示例的 Agent 判断与业务结果均为模拟，不调用真实模型，也不执行实际训练或预订。

## 模拟场景脚本

- [`acceptance.py`](acceptance.py)：通过 HTTP 演示研究任务独立推进、追加批次，以及差旅变更、暂停、通知和事件。
- [`package_acceptance.py`](package_acceptance.py)：构建并安装 Loop 包，验证从包运行的流程。

先查看脚本 `--help`，为场景使用独立服务和数据库。场景会创建 Run 并保留执行记录；它们用于主动演示，与默认测试的临时工作区不同。

作者业务内容与平台 Skills 分开。示例证明通用运行机制，不表示这些业务已经具备生产环境实现。
