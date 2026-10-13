# 20\.认证智能体PRD

# 一、 版本信息

版本号：V1\.0\.1

创建日期：2026\-1\-21

负责人：田媛、赵庆超

# 二、 变更日志

|**时间**|**版本号**|**变更人**|**主要变更内容**|
|---|---|---|---|
|2026\-2\-25|V1\.0\.1|田媛、赵庆超、刘健男、李超、李君岩、于晓冬|根据第一次PRD评审结果，更新章节六功能详细说明<br>|
|||||

# 三、 文档说明

## 名词解释

|**术语 / 缩略词**|**说明**|
|---|---|
|PLM系统|产品生命周期管理系统的简称，是管理产品从概念构思、设计、制造、销售、服务到最终报废的全生命周期中的所有信息、流程和应用的集成化数字化管理平台。|
|||
|||

# 四、 需求背景

## 背景

在认证全生命周期中，物料主数据维护、资料准备、审批流转、报告校验及有效期管理等关键环节仍高度依赖人工操作，成为制约效率与质量的核心瓶颈。以AI智能体手段助力认证流程，实现“数据—资料—审批—获证—预警”全链路闭环管理，是提升认证效能与可靠性的关键支撑，亦已成为行业演进的主流方向。

## 目标

开发一款认证AI智能体，解决繁琐的认证资料人工准备和整合、大量文档内容的核对、认证证书和报告有效管理，认证费用分析等痛点问题，实现认证工作全链路闭环管理，达到认证工作提质提效。

## 用户

面向研发工程师（结构、电源、电路、光学、声学）、认定工程师、认证工程师、认证管理人员等认证业务相关人员。

## 使用及价值

完全消除认证业务痛点，预估节省认证8000人工时，防范认证一致性检验不合格问题发生。

# 五、 功能列表

# 六、 功能详细说明（UXD）

本章节第 6 章功能详细说明是PRD的核心，梳理现状业务是如何做的，规则是什么，输出业务SOP，能够教新员工一样清晰，然后写出需要AI做什么。

## 提出认证需求@李超

- **角色：各产品线外销整机产品经理**

- **场景：自动抓取系统已有信息生成认证申请单，取消产品经理人工手动选项，重复填写。**

- **需求：产品包需求说明书发布后，产品经理****手动****点击“创建认证申请单”功能，自动抓取产品包及PLM系统中相关字段信息，生成申请单草稿。**

１\.制定基于产品的销售区域和产品种类自动抓取认证种类及相关工厂等信息，自动识别需要做哪些认证后输入产品规格书；

\-\-产品经理可通过多维表格方式首先建立知识库，其次实现产品包的结构化／产品规格书单独文件存放在产品包中而非嵌套；产品经理通过规格书中的出货国家、XX等信息；

——明确规则，AI可以协助完成自动填写

２\.**产品包需求说明书发布后，产品经理手动点击“创建认证申请单”功能，自动抓取产品包及PLM系统中相关字段信息，生成申请单草稿。**

3\.需要产品经理手填项目仅限认证报备型号；

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ODE0YmYzMDk4ZDJhZDczMTFlYjNkMzIxMWYxYzc4ZTdfYTgzNTY3ZTgyNTdkZThkNTdiZGJlYWIwZjIzYzBlZGZfSUQ6NzYwMDk2NzQwNDk0MDIxNzI4Ml8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZjUwZWJiZTA0YTg1YTEwOGU0NmUxY2JjZGFmNmZiOTZfZTkwYmI2YTllYWQ4MjNjNzQ0NmUwNDZjZjIwOGEzM2VfSUQ6NzYwMDk2NzkxMDE0NDQ3ODQxM18xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YWY0MDc3MjFlZDVlYTU5ZTcyYjhlZmQzOWFhYmVjZmNfYTYzZjk4ZTVlODdkMjkzMzY0NTZkNjk3ZjJiYjM4ODNfSUQ6NzYwMDk3MDMwOTcwMTQzODY4MV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

产品名称：应该是如“液晶电视”而不是机型

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZTlhZDEyNzhmNzE4ZmFlNzg4MDBkNGMyM2Y5NGU3YjJfY2MyY2RlMDRmNTcyZDFjMDQxZTlmMTNmMTY3Yjk0MTJfSUQ6NzU5ODkwODIwNDI4NTg3MzExNl8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

对应申请单，列出表格，一一对应说明

机型手动选择，CB国家差异、报备型号由产品经理手动输入；

认证类型默认“全新”；——删除，PLM

认证类别详见产品规格书“安全和认证要求”项；

报备商标取自产品规格书“品牌”项；

持证人：固定；

制造商：固定；

生产工厂：固定；

电压范围取自产品规格书“电源及输入范围”项；

**建立Excel表格：要求有字段名称、现有申请单的优化项（增加、删减的内容）\+对应的信息获取位置**@李超@王品

\[产品规格书\-98Z570SP\(01\)\-20260126\.xlsx\]

\*前置条件：产品规格书需要放置到规格下的第一级文件中 或 规格书结构化， 项目管理智能体@李烨


2\.**经产品经理审核通过后，点击“确认”后**自动触发PLM系统“认证申请单审核流程”生成初稿，按照原有审批流进行以下角色审批；产品经理确认**只保留硬件和认证工程师****。 **

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTY3YWI5YTRkOTBmMTcxOGM1MWYwZDJiYzI0NWEyZjNfYWU0NzRjZDMyNWVmNWJhNDM5MmQ5MjJhNDQ2MGVmNmFfSUQ6NzU5ODkwNzQxNjMwNjA5MzI3OV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

## 产品认证计划制定——项目WBS计划智能体 @闫伟玲

## 准备认证资料

### 产品认证\-内销

#### CCC认证 @刘健男

##### 全新

**1、导出关键件清单**

- 角色：电路工程师，电源工程师，模组光学工程师，结构工程师，认定工程师@刘健男@李超@辛惠莹@李君岩

- 场景：导出关键件清单

- **需求：PLM系统生成的关键件清单文件，****AI依据规则（如果规则变动，规则库更新）**

\[产品认证关键件清单及照片V3版\-原始版本\.xlsx\]**，审核，输出审核结果。**

PLM系统→认证管理→认证资料包→选择对应的认证资料包→**生成关键件 清单文件**

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MDc4ZDA2MTc4NGE2MTIxNDRiMTFiMTFmZjFjNmMwNWZfNzdhMTZhZDdjNTllZDQ4NTFiYzBmM2QwYmU4ODc2ZDBfSUQ6NzYxMDM1NDg1OTUxNDA4ODM4OV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

\[75VX5S\-PRO\(01\)\_安全\&EMC关键件清单\.doc\]



![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MDBhM2U1YTljNjk3MDJmZWNhZWM4OWRmMTYzZDFmMjZfMjFlOGIwODk3NjMzZGVmNDQ2YTkxMzFmN2QyMGVlYTZfSUQ6NzYxMDM1NjMyNjYxNDg5NTg0Ml8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTc3ZTdkNjlmZjg1MzNiMzIwOGRhYTFiZjJmMjdjZTJfYTQ5ZGQxMWEwNjFhNGVlNzI0M2NhOWFlMzBmNTE2NTNfSUQ6NzYwMDk5MTAzNDg2ODc2Mzg2MV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)



**价值：****①**节省电路工程师收集、整理CCC《安全\&EMC关键件清单》所需时间，0\.5H/项目，提升工作效率。②提升新品一致性检查合格率、降低量产品一致性检查问题数、减少停产和翻包损失工时。

**验收标准：**《安全\&EMC关键件清单》

**2、****~~ 关键件清单信息审核及修订补充 ~~**@李君岩

- **~~角色：认定工程师~~**

- **~~场景：~~****~~审核安全\&EMC关键件清单、整机安全件清单中~~****~~关键部件~~****~~二供~~****~~信息~~****~~，~~****~~缺失补充~~****~~，错误纠正~~**

- **~~需求：~~**

- **~~①根据PLM系统整机BOM清单，AI自动识别~~****~~关键零部件~~****~~料号和品类信息~~**

- **~~②AI自动比对安全\&EMC关键件清单、整机安全件清单中每个关键件认证信息是否与零部件认证信息库存在差异，提供差异说明并通过认定工程师确认~~**

- **~~③如有差异，则需要认定工程师补充/修改认证信息，可选择是否更新为关键零部件认证信息库认证信息，或者手动更新~~**

~~①收到OA流程，打开安全\&EMC关键件清单、整机安全件清单，查找负责的关键零部件信息~~

~~②检查~~~~本次认证的“关键件清单”中~~~~关键零部件的二供信息，型号、规格、厂家名称、认证标准、认证型号是否与零部件认证信息库一致~~

~~③根据产品不同认证类型，CCC\\CB\\UL\\S\-MARK，确认关键零部件是否可以直接interchangeable、列1家\+interchangeable，还是不可以interchangeable~~

~~④如一致，则审批通过~~

~~⑤如不一致，需下载后手动补充/修改二供信息，标记颜色或者增加备注，再将修改后安全\&EMC关键件清单、整机安全件清单上传OA系统~~

~~⑥如涉及当地认证或特殊认证，还需要提供二供规格书/认证证书~~

- **~~价值：减少人工~~****~~审核、补充时间，0\.5H/项目，提高工作效率~~**

- **~~验收标准：关键部件完整信息~~**

##### 变更\-开发@刘健男

新机型变更认证选取变更原证书，现状是各专业沟通依据产品规划、是否同电源板、是否同主板等综合确定。

角色：电路工程师，电源工程师，模组光学工程师，结构工程师，认定工程师

场景：各专业对比原报告，整合输出变更后的关键件清单

需求：**PLM系统生成的关键件清单文件，设计将清单文件与派生原报告清单文件输入AI智能体，AI智能体实现两份文件整合（重复资料合并，非重复资料整合并标红加粗，备注资料来源自哪份文件），并生成一份汇总版关键件清单文件，同步生成变更前后对照表**

PLM新生成清单文件：

\[75U66Q\(01\)\_PLM导出清单\.doc\]



派生原报告清单文件：

\[75U66Q\(01\)\_原报告清单\.doc\]



需要的结果：

**1、变更后的关键件清单**



\[75U66Q\(01\)\_安全\&EMC关键件清单\.doc\]

2、变更前后对照表

\[75U66N变更前后对照表\.doc\]

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZjNmNTY3NzhlYzJkOTY1NDg3ZjE5NmU2Y2ZlMjYwN2NfMzBjYmNiMDYyYjFiNmVhMWNiMGE3OGUzOWE3MDljODhfSUQ6NzYxMDMxNDIxMTM3Nzg1OTc3Ml8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

将整合后的关键件清单\+变更前后对照表\+增加变更型号的企业承诺书和型号差异声明\+新型号铭牌资料汇总后，提交KOA 3C认证变更流程，经各模块工程师\(确认资料准备性\)和认定工程师\(完善扩点资源\)审批后，交由认证工程师发起新型号的认证变更申请。

- 角色：电路工程师、电源工程师、产品经理、认证工程师

- 场景：AI自动推荐新机型变更认证选取的变更原证书

- 需求：根据新增型号，AI对比PLM上相同电源板、主板的型号，制定规则，推荐并选取差异化最合适的原证书型号。

- 价值：减少各专业的反复线下沟通，快速确定原证书型号，最大化减少认证费用

- 验收标准：输出原证书型号

##### 变更\-物料扩点

- 角色：认定工程师@李君岩

- 场景：物料扩点 ，使用频次：大约 1个物料号查询500个机型，年物料号大约100个，一个机型查询约0\.5小时。

- 需求：

    - AI自动排查扩点的物料涉及机型、整机状态、整机销售国家， AI

    - AI根据机型排查证书报备现状，确认每个机型证书关键件清单是否包含拟扩点供方安规信息，AI，存在技术难点（PDF文档）

    - **AI提取未报备拟扩点供方、型号的机型清单**，AI

    - 每个机型AI自动生成需要认证变更的安全件清单，**输出简化备案评估表，AI**

1\.通过PLM系统根据扩点**物料号**反查所有应用机型型号，清单导出，以压敏电阻为例（图片）

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=Y2VlYmQ0NGFkMjE3NDI4Nzc0NzhiNTc1NmNjNTUwYjZfNWI0ODNlNWY2NWExMzJiZmY0NzcwZmYzMzVkZTdmMzFfSUQ6NzYwMjA4MjkwNDIxMTAzMzA0MV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

2\.将导出的涉及机型清单给产品经理，确认在产机型明细，输出在产机型清单（线下→AI）\*确认PLM系统中是否有字段确认？是否有明确的确认规则？ AI

规则：

PLM系统导出的机型清单中“状态”字段有立项、开发、上市、退市，所有者对应的是产品经理，状态为“退市”的可删除，但是防止退市机型有尾单，**可参考SCP系统13\+9计划****（接口确认）**  AI

机型清单后面空白增加两列“证书号”“报备状态”

3\.输入给AI智能体：需要扩点的物料信息，型号、规格、厂家名称、证书号

举例：拟扩点厦门万明的压敏电阻，给AI智能体输入如下信息

4\.根据在产机型清单，在认证工程师共享云盘中（后续建立云文档多维表格或PLM系统）逐一排查机型认证报告上**是否已包含拟扩点供方认证信息**

场景1：认证工程师管理

①确认机型所在产品线，以上图65E5N为例，属于CN产品线

②打开认证工程师共享网盘，找到CN产品线文件夹，找到A系列

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YmUxMDQyNjM4OTU1ZjVkZTNiNWFmYWNmYzA1NjMxOTVfMWQwMDE2OGNkNjJmZjc5NTRhNmU5ZDgzZThkZDdmNGZfSUQ6NzYwMjA5MDE0MTQxMTQ0NTk4M18xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

③打开CCC认证，找到65E5N

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZWRkZTkyYmMwMmJhNmVmZGM3NmU3OTdjNDZmZWY3ZGVfOWJhZGJiZmI0ZmU5ZDllMTgyNGI0ODdjN2UwM2UxY2FfSUQ6NzYwMjA5MTQ3NTA5MDQxMDcyMV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

④找到该机型的证书号和《国家强制性产品认证试验报告》

证书号：2024010808681857，记录在进行清单“证书号”列，如未找到证书号，则“证书号”列记录“/”，“报备状态”列记录"未找到该证书"

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MzM4MzMzNjQ2MDI4YzVjNDAyYTUxMjQyZWU5MzVjZjdfM2NkOTcwNjBlZWEzNzBkNDA0NzlhZmRkMGFlNTc5MTJfSUQ6NzYxMzI4NjQwNTA2Mzg3MTcwMl8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

⑤找到《国家强制性产品认证试验报告》中压敏电阻的报备信息，确认是否包含拟扩点供方认证信息，如包含，则在机型清单“报备状态”列记录“已报备”、如不包含，记录“未报备”

扩点时供方名称是确定的， 但涉及到文件的内容格式和PDF文件AI解析准确率（技术难点）

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZmRkOTRlYWViYWVhOWZhZDdlNTVjMmQ0MjNkZmZlMTZfZGU4M2M1NmVkY2I4NmI4NTQ4OGRhYzQxMzYzYzg4OGZfSUQ6NzYwMjA5MjUyMjY5MzI0OTk4NV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

⑥将机型清单“报备状态”列记录“未报备”的，提取出该证书号仅包含该关键件的清单，word版本，示例如下，此为变更前清单，需AI导出，

（注意一个《国家强制性产品认证试验报告》中关键件清单可能带多个电源板，关键件名称存在重复，需要都提取出来）

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OGJlYmYxZmVkODBlMDZjZTRiYzE2YTNkZGU5OWJlMjBfZTZkNTY4ODY0NDUwZTU3ZDNkMDNkZjBmMDc1NzBiZGNfSUQ6NzYxMzMyMTQyODQwNjk5NjE1M18xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

⑦将每个证书号变更前清单，在下面增加行，添加拟扩点供方认证信息，word版本，示例如下，此为变更后清单，可人工添加

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ODhiYzFmMzE1ZTgxMzM1M2UxZWM1MDBhNWY1N2Y3MTNfMTRlYTYwM2M0MWJhOWZlYzM5NGRlMjZjN2ViMjE2ZTRfSUQ6NzYxMzMyMTU0MTU2MDQzNzcwMV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

场景2：市场当地转认证，例如印度BIS认证，台湾BSMI认证，需要找对应的产品经理要认证报告，操作内容同上  \*需要产品经理对认证报告进行统一管理

**5****\.****提取出报备状态为“未报备”的****机型清单****，按相同证书号分类整理成sheet2****\-AI输出**

机型清单（含内外销）、认证类型、认证号、认证文件@李君岩

6\.认证类型是CCC的，查询**CQC\-C0901\-2023《强制性产品认证实施细则 电子产品及安全附件》，确认扩点品类的**关键件等级，ClassA or Class B， 人工确认

\[CQC\-C0901\-2023《强制性产品认证实施细则 电子产品及安全附件》\.pdf\]

①如扩点品类是Class A，需要每个机型一个流程

②如扩点品类是Class B ,走CCC认证B类关键件简化备案流程，填写变更表，经研发专业人员和认证技术负责人，部门领导审批确认

提供word表格@李君岩，AI输出

通常扩点关键件为classB等级，需根据每个证书号生成一个《CCC 认证变更简化流程申请及评估表》

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MzcyN2M1NjViMjUzYWU5MWEzMDRmNTdiOWQ4YzFiMWFfMDg5MTA1ZjVhZDhmM2VkODMyYTYzMWRjNTRhN2IxMzBfSUQ6NzYxMzMzMjAyNjI1MTA3MDY4M18xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

\[GYZ002\-R01 CCC认证变更简化流程申请及评估表 V1\.0\.docx\]

认证类型是外销，CB、UL、S\-MARK等，需要每个机型一个流程

7\.将机型清单按认证类型分类，找不同认证工程师核算测试费用 （不需要）

8\.费用给供应商确认承担后，发起认证变更流程。（不需要）

- 价值：减少人工排查，减少遗漏风险，25000H/项目

- 验收标准：安规物料扩点无因认证问题导致整机一致性检查不合格

- 认证：全认证通用

### 产品认证\-外销

#### CB认证 @李超

##### 全新

**1、导出关键件清单 **

- 角色：电路工程师，电源工程师，模组光学工程师，结构工程师，认定工程师

- 场景：导出CB《关键件清单》、制作认证铭牌、排查派生差异。

- 需求：

**1\.****同****CCC，PLM系统生成的关键件清单文件，AI依据规格审核，输出审核结果。**
2\.根据提供的模板，填入机型及功率信息，自动生成并提供认证工程师铭牌。

铭牌模板参考如下：

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OTdmYWY3MmJkY2ExOGU5NDczNTA4NWM4ODk1N2QzOWFfM2RkYzYxNjJjNjIwNGQ5OTg3NjA2YWIzZWI3MzkwMTNfSUQ6NzYwMjE3Njc2NDA3MzQzMDIzNl8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZDNkMzkyMjFhY2Y2Mjg1ZTM4Y2ZmODU4NTZjZTdlMzRfZjA3YTNhOGI2NmRkN2NiZWFiNGEwZTFjN2YwMTczODBfSUQ6NzYwMjE3NjQ4MzIwMDkxMjU3MF8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

和内销差异，电路工程师输入型号之后，自动从对应型号的1TE BOM中的1063886物料号的项目文本抓取最后的电压和功率值信息，如下图，并根据提供的模板生产对应的认证铭牌

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZmM5ZjYyOTljZDU2NzIyMWJkMzc3NzI5NGM2MjNjOWZfNDU5OGZjNDQ4ZGMxNzZmMWMxMjFhNjBkYjM5NzBlMTdfSUQ6NzYxMTQ1Nzg3MjAxODg2OTIxMl8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

3\.AI自动比对BOM使用的电源板部件与PLM系统中所有机型电源板部件（仅比对EU和AP所有机型）比对，找出差异最小的电源板部件，提供差异说明并通过电源工程师审核，审核后传递到电路工程师。@李超

a\.找到要做认证的机型1TE BOM中使用的**电源板部件组件号**；

b\.在该组件号下找到被产品引用的所有的产品，并提供说明“AP或EU产品线的\*\*\*机型使用相同的组件号”，如下图：

返回结果：产品线、名称、状态。

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZWRmMzMzOTAzMDdhMGE2MTFkYWEwZmRiZmEwZmMyZmJfYzk3NGFmZmM3YmViMDc1NWNlYTIwMDI2NzY5M2UxOWNfSUQ6NzYwMjE3OTU3NDkyMzk1NTQyMl8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

c\.**如果****“****状态****”****不是上市的**，需要找到当前机型的电源板部件的贴片单元下的零部件细类为“**单层PCB板”物料**，并找到被产品引用说明，如下图：

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YTY3ZTk3YzkzOTc4OGYzN2VjYTJlMTczMGRlZmMzNDJfNzU2OWU2N2FiYTkyODk4NGE3NTk0ZGI1ZWY2YzhlZDhfSUQ6NzYwMjE4MDE1MTUyMzM0NzY4MF8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

d\.找到AP或EU产品线的机型，并检索对应机型下层的电源板部件组件号，**按照位号**比对电源板组件下的所有物料，找到最接近（规则：和要做认证的机型的电源板组件的差异物料数量最少的）的Top5个组件号。并反馈“AP或EU产品线的\*\*\*机型使用相近的组件号，具体差异是：位号R11与位号R12的XXX不同\*\*\*\*”

返回结果：产品线、名称、状态、TOP5差异清单

- 价值：节省电路工程师收集、整理CB《关键件清单》所需时间，1H/项目，提升工作效率

- 验收标准：CB《关键件清单》，铭牌，派生差异说明

##### 变更\-开发  同CCC

##### 变更\-物料扩点  同CCC

## 审批认证申请

- 角色：认定工程师@李君岩

- 场景：变更认证申请时，涉及到非导出的关键件清单，制定规则，AI辅助审核。

- 需求：审核认证资料时，AI对比审核，汇总输出。

打开认证资料中的关键件清单（word文档），和**认定工程师的零部件认证信息库（excel表格）**AI对比，识别差异内容，认定工程师确认。 通过AI实现。

比对规则：

1）包含“关键件名称” 保持一致、型号、规格/材料

2）以**认定工程师的零部件认证信息库为基准，检索条件为：（关键件名称\+型号\+规格）作为检索标准，逐个分别将关键件清单里的内容进行逐项比对。**

a\. 比对内容完全相同: 不作处理。

b\. 比对内容不相同：

\- **零部件认证信息库的记录在关键件清单中不存在，则将此记录添加到关键件清单中。**

\- **零部件认证信息库的记录在关键件清单中已存在，但内容不同，则标识差异部分的文字（显性以标颜色或其它方法进行展示）**

**场景1：CCC认证**

1\.OA系统收到海外认证、国内CCC认证、节能认证资料审批流程待办，打开安全\&EMC关键件清单

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OGZmZDUwN2UzMjIxNDFkYTY0NDJlM2FmOGQwNzZkMGJfYjVkYjk2ZWRkZWQ3ZDdkNDEzYjg5MTMxZDBlYTVlZWRfSUQ6NzYxMTA4OTMyOTA3MDU1ODE0Nl8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

3\.根据关键件名称列找到认定工程师各自负责的品类

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YjRiNTE5ZDQyM2UwYjJiY2ViMzdiYmY0ZTRjNjVjYzVfZmUyYTQzMjBiNmZjZjg5ZmYxMjA3MGJhNjVkYmE2M2VfSUQ6NzYxMTA4ODAzNTA0MDAwNTA4NV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

4\.以PCB为例，找到PCB品类，认证类别为CCC，所以打开零部件认证信息库[电源电路部分安全件报备清单明细表\_认证类别CCC\-20231110\.xlsx](https://hisense.feishu.cn/file/ViaXbTUULolN8xxG7jYc6ekenIf?from=from_copylink)，找到关键件名称为PCB，逐一比对型号、规格、厂家名称、认证标准、认证证书号是否与信息库一致，若有不同，根据信息库内容修改安全\&EMC关键件清单，字体颜色标红，增加批注

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MGE0MzMxMGE0YWRlOWMwZTdjZWE5MTY0ZDc1OWQzMzZfNWY1MmRhZjFiODE4YTFjMWMzYWQ0NDc3OTljZjk2NjBfSUQ6NzYxMTA4ODI3NzQwNzgyOTIxMV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MDRhYzMzOGNiZWFiNzVkZDY5MjcyNDM5N2QyYTZiM2RfYjc3ODYzN2Y3NzQ4MDZmMTg2MzA3ZDAzZTc2M2ZhYjFfSUQ6NzYxMTA4OTAyMjI0OTQ4NzI5MF8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

5\.将修改后的安全\&EMC关键件清单上传到OA系统，流程审批通过

**场景2：外销（CB\\UL\\S\-MARK）认证**

1\.OA系统收到海外认证、国内CCC认证、节能认证资料审批流程待办，分别打开电路清单、电源清单和结构清单

https://koa3\.hisense\.com/oa/km/review/km\_review\_main/kmReviewMain\.do?method=view\&fdId=19c2120201039158d89063943bf8f1c9\&fdTaskInstanceId=19c94134622dae0a7a97f364c719e4ab

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YTMzYTkyMTY1YjNkYTYxYWMwNDQ3NTRkNzlhYTUzNWZfODdkMzM5ODcwZjYxZjhlY2I2NzJmYjA0OGM1Y2YwZWZfSUQ6NzYxMTA5MjM5NzgwNDM5MTYyMF8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OTJmM2QyMDhkMzVlODExNDc3YjUyMzFmZTA3ZGNiOTNfOWIwZmVhOTAwNTZlODFlYmQzZDljM2NlY2JlZGFmMWZfSUQ6NzYxMTA5MjQ5NzQ4MTY2NTc2MV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

2\.以保险丝Fuse为例，打开电源清单，找到保险丝Fuse，同时打开[电源电路部分安全件报备清单明细表\_认证类别UL\-CB 20230420\.xlsx](https://hisense.feishu.cn/file/GpsFbMwy3oDZIHxylWPcLYb7nGg?from=from_copylink)，

①找到型号为UDA\-P，规格为T6\.3AH250V的保险丝，确认商标/制造商、认证标准、出口认证证书号是否与认证信息库一致，如不一致，需下载下来手动修改

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=Zjk1M2U5MTRlYmE4ZWEzNjQxMmQ4YjJlMGRjZTljNzdfNDk3ZDgyMzc4ZjUzMjY3MTg1Yjc2NTI1MjM0Njk5M2NfSUQ6NzYxMTA5MzA3Nzk3MzA2MDU0OV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YTVmNTBmNDUxODllNDU2M2JiN2Q5ZmIxN2Y0YTIwM2ZfYzJlZGRmODNhZjNlYzFjODcwMmE4NjBmNTgyMWFiZmFfSUQ6NzYxMTA5NjE2MTk1MzI4NzM4MV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

②再确认两个清单的差异项：电源清单中是只报备了一家\+interchangeable，而[电源电路部分安全件报备清单明细表\_认证类别UL\-CB 20230420\.xlsx](https://hisense.feishu.cn/file/GpsFbMwy3oDZIHxylWPcLYb7nGg?from=from_copylink)，有三家，另外两家是否需要补充

规则：@李君岩

1列一家\+interchangeable： 比对内容与其中一行完全一致即可

2不可interchangeable：比对内容需完全相同

3直接interchangeable：不做处理

4列多家\+interchangeable：比对内容需完全相同

③根据产品认证关键件清单及照片V3版\.xlsx文件规则，找到SMARK认证sheet，报告中FUSE可以列一家\+interchangeable，确认无需补充

\[产品认证关键件清单及照片V3版\.xlsx\]

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZmE0MzEyZTZhOTBjMjE4NWMxYmI5MjU4NjU4MTcwNmJfMzRmNjMyMmE1OTg0NDJmYTA1M2QxNDJmZDA3ODkwNzNfSUQ6NzYxMTA5NjU4MTcwMTYxODYzNV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

④以上两项确认完后，若不需要修改，流程审批通过；若需要修改，则将修改后的清单上传至系统，流程审批通过

## 确认报告草稿准确性 

全部产品线、各专业确认@刘健男@李超@辛惠莹@李君岩

- **角色：电路工程师，电源工程师，模组光学工程师，结构工程师、认证工程师、产品线总经理**

- **场景：核对认证报告草稿准确性**

- **需求：核心内容：比对并输出差异。自动比对海信提供的认证资料和认证机构的报告草稿文件信息是否一致，并输出比对的差异点结果，差异点需要明确标识（需要两种标识方式，一个是报告草稿清单中，需以批注的方式标注差异项，另外需要汇总所有的差异项，按1、2、3的顺序写明，用于审批人确认），****AI **

1）报告草稿附件上传KOA/Tims流程后，发起审批流程，由各专业人工审批报告草稿，并在审批意见处写明修改项或者上传需要修改的附件。

2）认证工程师收集修改项后，汇总修改内容，发认证机构修改（通常需在word版报告草稿表格中备注好修改项，并在邮件里写明需要修改的内容，）

3）认证机构修改完成的报告草稿，发内部二次审批。循环以上步骤，直至全部修改完成。

\[100E7S\-PRO\(01\)\_安全\&EMC关键件清单\.doc\]

\[A2026CCC0808\-4944044（00501\-CG2026\-0353）\-P 安全描述\+EMC（1\.26）\.docx\]

之前有过类似对比系统http://10\.18\.219\.171/llm\-platform/\#/doc\-verification

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=Yjk4MDNiODQ5MDNmMjg5ZTZiYTExYTE1M2M5MTYyNDBfY2U4MzRkNDdhYTUwMjU3OGI3OTY3OGJiNTBjMDY0OWZfSUQ6NzYxMTM0ODQzMzQzNzMzMDM3MV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

- **价值：节省人工比对时间，0\.4H/项目，提升工作效率。**

- **验收标准：准确性比对结果**

- **认证：CB、CCC、零部件、全认证通用**

~~\*论证确认后续是否需要认定在此环节确认~~@陈善幸@赵庆超

## 归档、管理、更新证书和报告

- **角色：**认证工程师@赵庆超

- **场景：**获证以后的证书、报告（整机）的归档及查阅、有效期管理

- **需求：**证书\+报告的自动统一归档，把多维表格里的证书和报告同步到**云盘\+档案管理室\+PLM系统**，减少重复性工作，自动管理和预警证书有效期、到期前自动发起延期申请、认证相关人员可自行查阅。

1）证书获取后，登陆云盘系统、登陆档案管理系统、登陆PLM系统，上传认证证书和报告

a）本地证书管理：

证书报告保存个人电脑本地地址存放，并维护产品认证台账，创建台账与文件的超链接，用于后续认证工程师，认证工作的使用（比如派生关系查询，证书信息快速查询）

b\) 证书报告线上管理：

信鸿→云文档→云盘→产品认证室，找到相应的产品线文件夹，找到对应的尺寸文件夹，找到对应的机型文件夹，上传证书和报告；

将本地台账表格上传云盘，用于研发人员查询使用

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ODgyNTUxMWM5ZjQ0MGRlMjM2YzlhYjkyZjdmMGZkODdfOGU3NDFjNTEzZGQ4ZDcwMDUzMTIxM2MzYTQxYTI4MDBfSUQ6NzU5OTg2NTI3NjIxMzcxMDAzOF8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

c）PLM系统证书报告线上管理：

证书报告上传PLM产品认证中，并填写产品认证属性，用于产品主数据的关联使用（将来替代b））

d）集团档案室管理（零部件不涉及）：

网址：

对接的系统需要开放API接口

证书报告，以及相关的属性信息，录入集团档案室，用于后续市场、各分公司等证书借档使用。

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YzM0NTFhOWM4ZGE3ZmRjYzQ5MjI0YzRmMmNlOWYzZDFfMzMxNDJhMDdhM2RjYjhkNDk0NGI0YzdjNGM1NzAxNWJfSUQ6NzU5OTg2NzYwMzM0ODExNDM2NF8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

2）证书有效性线下人工根据自己的管理方式记录及排查

- **价值：**减少重复工作，自动有效期管理和预警，方便查阅，0\.2H/项目

- **验收标准：**证书和报告管理平台

- **认证：**CB、CCC、零部件、全认证通用

## 要求及接收供方更新认证信息

- **角色：认定工程师**@李君岩

- **场景****1****：安规物料扩点时，二供供方源头的基本信息维护****  \*前提条件：功能实现。\-\-已确认 SRM和PLM对接的功能实现了（白电已使用）**

- **场景2：供方认证信息发生变更时  **

- **需求：****AI审核****供方填写的信息：****证书号的存续状态，型号、规格、标准是否与证书内容一致，传递审核结果**

AI审核结果输出后，经认定审核，结论通过或驳回；

- **场景3：供方认证证书有效查询**

- **需求：自动识别零部件信息库中安规证书有效性，在临期前一个月、或异常暂停时通知认定工程师处理**

①打开共享云盘零部件认证信息库

云盘链接https://hisense\.feishu\.cn/drive/folder/GYWSf5kGmlgivCdPcNCc6Vzinth

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTE5ZGE2OGU3ZDViZjRiNDVkNThhYzk2NjJiM2EwOTBfMTc1ZWZlZWIyMGQzY2I4ZmYwZDQxYmJlM2MzOGFhZGNfSUQ6NzYwMjEzMDIyNjEwNTE5MTM4Ml8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

②打开报备清单，根据认证证书号，登录对应查询网站，逐条输入，查询证书型号、厂家名称、认证标准和存续状态是否与网站一致

**打开文件1 **[电源电路部分安全件报备清单明细表\_认证类别CCC\-20231110\.xlsx](https://hisense.feishu.cn/file/ViaXbTUULolN8xxG7jYc6ekenIf)

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZDU3MDIxMGEwYzMwNTRmYzgxYWVkN2RiYWY4MTZhNGNfYzYwYTQ0MzYyMzQyZTc2OTU2MjQzOGVlNDY1MDRlYWZfSUQ6NzYxMDk3MDg4MzMxMzk2MjE4Nl8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

③CQC查询网址https://www\.cqc\.com\.cn/www/col5/index\.html  无需账号，需要验证，根据I列证书号逐条输入，查询结果中制造商、生产厂、型号、标准、证书状态是否与CQC网站查询结果一致，输出结果到L列，注意有2个sheet

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NDQ4NTczY2VlZWNmY2Q3NTdmMTNmNjEwZDliMWVhMzdfZTQ2NDdiZTU5Yzc3MjQxMWQxZmZlYjU4ZjdkMjRmNjBfSUQ6NzYwMjEzMzAwMDUxNzI3NDgyMF8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

④强制性认证产品符合性自我声明的查询网址http://cx\.cnca\.cn/CertECloud/index/index/page，无需账号，需要验证

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MThlODI3ODEzNTU5YzZlZDVmODQyNzE4Y2FkZmU4YmFfNmQ2NDRmMjM2M2NlOTVjZGE2N2ZkZDlkODA1NWQ5OTFfSUQ6NzYxMDk3NDM0NTg1ODg3ODQwM18xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YzhiMjQ5MzM5ZTI5YTNhODQxZmYwNTIyM2Y0MWVjZjhfYzkxN2YyNzUyYjA4MDk0MmI4ZTM5MzQ4YTMyNDkwYzhfSUQ6NzYxMDk3Njk4NTIyNTE1MzQ3Nl8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

⑤**打开文件2**[电源电路部分安全件报备清单明细表\_认证类别UL\-CB 20230420\.xlsx](https://hisense.feishu.cn/file/GpsFbMwy3oDZIHxylWPcLYb7nGg)根据I列证书号逐条输入，查询结果中制造商、生产厂、型号、标准、证书状态是否与VDE\\UL\\TUV网站查询结果一致，输出结果到M列，注意有2个sheet

VDE查询网址https://www\.vde\.com/tic\-en/marks\-and\-certificates/vde\-approved\-products/search?search\_t=name\&page=1\&certificateNumber=40052271 无需账号

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NmQ5OTVjOTZmY2NjNjgxOGIyNmNlZDQ0NDAzMmY1MGJfNjQ5YmIwZGJmMGExMTgzZGMzZDhiY2M0N2FhOWM0ZjRfSUQ6NzYwMjEzNDU5MDcwMjUzNzk0N18xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

UL查询网址https://iq\.ulprospector\.com/en?bplogin=success 需账号和密码

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZTE1N2NhMmRhOGQ1NDkwMzc5NGY3NzM4NDA3MWU3MThfNGM4YThmNjAyM2Y2NTYxYzcwM2NlY2NhYjhhM2IxZThfSUQ6NzYwMjEzNjM2ODgzNTQ5NzE2NV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

TUV查询网址https://www\.certipedia\.com/certificates/50050155?locale=en  无需账号和验证

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ODc4NWM0ZmY1Nzc0YTQ1ZTZiOWVhYmM0MDZiZWU1NGNfMGJjNDhlYzY0Y2MzMTJmMzliYmUzYzFkN2RmZTUzODFfSUQ6NzYxMDc0MjcwNzg4NzIyOTg5OV8xNzg0MjY5Mzg1OjE3ODQzNTU3ODVfVjM)

⑥**打开文件3**[原材料安规报备\.xlsx](https://hisense.feishu.cn/file/UMN5bjvqWoKEHPxWtwhcbu98nIc?from=from_copylink)，

sheet1为CCC安全，根据J列认证证书号，在CQC网站查询，查询结果输入M列

sheet2和sheet3为UL认证，根据I列证书号，在UL网站查询，查询结果输入J列，查询方式同上

⑦将查询结果差异项，邮件输出对应认定工程师

⑧认定工程师根据差异项，更新零部件信息库信息，如证书状态暂停，则对涉及物料进行处置

- **价值：减少人工的繁琐重复查询工作量，查询滞后，周期：每个月每个证书号一次，0\.03H/项目**

- **验收标准：自动化查询**

## 认证工作相关活动

### 费用分析——项目费用管理智能体@赵英芹

### 声明材料

- **角色：**认证工程师 @赵庆超

- **场景：**认证声明材料批量自动生成

- **需求：**将收集的研发资料，根据需要的模板（word、EXCEL）等，自动批量生成需要的声明材料，AI

1）研发通过KOA流程提交认证资料，

2）根据研发提交的认证资料、还有型号等信息，以及固定的模板，手动逐个填写资料，并转化为PDF文件

基本信息：输入或抓取

模板：提供模板，认证工程师可自行复用扩展

@赵庆超提供：模板\+源数据

\[环保声明申请信息模板\-75 85LASF，75LASF\(01\)\.doc\]

\[75LASF\(01\) TVS\_DeclarationSheet\_en\.xlsx\]

\[75LASF\(01\) Providing attached RoHS Compliance Declaration sheet\.docx\]

\[DOC模板\.rar\]





整合转化PDF

- **价值：**减少人工工作量，0\.1H/项目

- **验收标准：**符合要求的认证自我声明材料

- **认证：**全认证通用

### 认证指标看板

- **角色：**认证工程师、认定工程师、电路工程师，电源工程师，模组光学工程师，结构工程师、认证工程师、产品线总经理、管理人员 @赵庆超

- **场景：**认证指标看板，** ****需要及时性、符合性的原始数据**

- **需求：****AI智能体从认证多维表格、PLM系统、Tims系统中，获取实时的认证信息，判定认证目前的进度、以及周期、指标等信息，生成认证指标看板**

需要增加认证过程管理看板功能，管理各产品线认证申请及时性、认证资料符合性，指标如下：

XX产品线认证申请及时性－总指标；区分项目难度；

XX产品线认证资料申请及时性（第一批、第二批）

XX产品线认证样机提供及时性（第一批、第二批）

XX产品线认证申请符合性－总指标：区分项目难度；

XX产品线认证资料单机型平均变更次数、

XX产品线认证资料单机型样机准入符合度

需求：及时性指标，将PLM系统或信鸿3\.0系统提交认证申请时间抓取至项目管理助手－认证三级计划中的对应任务，自动更新状态完成并在多维表格中自动填写完成时间；认证样机提供及时性需从项目管理助手，认证三级计划中对应任务将计划时间、完成时间抓回；自动生成看板

- **价值：**呈现认证指标，推动改善和提效

- **验收标准：**认证指标看板

- **认证：**全认证通用

# 七、 非功能需求

> 性能特殊需求：超过性能标准要求的特殊需求说明
> 
> 视觉强调需求：需要强化用户感知的视觉点
> 
> 运营配置需求：比如哪些功能需要业务提供素材或者规则进行配置
> 
> 法律法规及安全需求：比如欧洲的GDPR，北美的加利福尼亚法规，用户隐私等
> 
> 

## **性能要求**

|**场景**|**指标**|
|---|---|
||时间≤50s；准确性100%|
||时间≤50s；准确性100%|
||时间≤50s；准确性100%|

## **可靠性要求**

•  **系统可靠性：100**%。

# 八、 数据与知识依赖

> 数据依赖：PLM系统中的结构化认证信息等数据；
> 
> 知识依赖：技术设计规范， 1\.5\.11\.2管理产品认证、
> 
> 



# 九、 IT系统依赖

> 此项目依赖于PLM系统、TIMS、云盘、档案管理室、云桌面、SRM系统、KOA系统
> 
> 



# 附录

> 输入 @ 把正文提及的具体文档，或需求相关的其他说明文档附在此处以供查阅
> 
> 

数据分析报告

- 此处插入数据分析报告

用户调研报告

- 此处插入用户调研报告

设计分析报告

- 此处插入设计分析报告



# 评审过程记录



# 最终评审结果





