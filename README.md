给多租户表加了行级安全谓词，结果查询里带一个空值就把别人的行也带出来了：三值合取把未知当假，空值行被误拒，与契约相反；三值析取把未知当真，空值行被误放行；求值把未知直接返回布尔，丢失未知状态；放行判定把未知当真，空值即绕过；空值比较按等号判定为真，空等于空被当成匹配；谓词合取按传入顺序短路求值，前一个未知后不再求值，结果不稳定；合取不去重，同一谓词重复出现导致行被排除；视图展开丢弃基表谓词，绕过行级安全；解析不拒绝字符串拼接，谓词文本可注入；批量判定复用上一次的行上下文，第二行沿用第一行的空值集合。rls/_impl.py 是核心，tests/test_predicate.py 15个红。要修的是：按上面的顺序把 10 个缺陷逐个修掉。

运行方式

在仓库根目录执行：

    python -m pytest tests -q

初始状态必须是 15 failed，并且 15 个失败全部是 NotImplementedError。不要修改 tests 目录中的测试。

字段表

运行环境：Python 3, pytest

契约要点

三值只有 true、false、unknown 三种，unknown 不是 false，也不是 true。
admits 只在 evaluate 返回 true 时返回 True，unknown 与 false 都必须拒绝。
combine 的合取与传入顺序无关，结构相同的谓词只保留一次。
expand_view 返回视图谓词与全部基表谓词的合取，基表谓词不能丢失。
predicate_batch 返回以行下标为键的布尔字典，每行独立求值，批与批之间不共享上下文。
parse_predicate 把字符串字面量当数据，拒绝字符串拼接、注释、分号和多余记号。
谓词比较涉及空值时结果为 unknown，空值只能通过空值判断处理。

门面布局

sec-row-predicate/
  README.md
  conftest.py
  rls/
    __init__.py
    _impl.py
    api.py
  tests/
    test_predicate.py

README.md：题面、运行方式与契约说明。
conftest.py：把仓库根目录加入导入路径，保证 rls 可导入。
rls/__init__.py：只从 rls.api 再导出 8 个公开名字。
rls/api.py：只做再导出，不包含业务逻辑。
rls/_impl.py：唯一实现文件，恰好 8 个桩，全部抛 NotImplementedError。
tests/test_predicate.py：15 个严格测试，不可修改。

## 字段表

| 字段 | 取值 |
| --- | --- |
| 所属领域 | 安全 |
| 子方向 | 漏洞检测与攻防 |
| 任务类型 | Bugfix |
| 语言/框架 | Python 3, pytest |
| 环境可复现等级 | 无外部依赖 |

