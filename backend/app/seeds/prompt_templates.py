"""内置提示词模板。

由 `python -m app.cli seed-prompts` 写入，user_id 为 NULL（内置、只读）。

几个写法上的共识，改模板时请一起遵守：
- **变量要少**。填 3 个空比手写一句话还累，模板就没人用了。
- **知识图谱 / 架构流程不指望模型把字画对**。这两类的模板统一要求"留白 +
  只画结构不写文字"，字由人在编辑器里补——这是当前模型的边界，别自欺。
- **负面词固定带上"文字、水印"**，省得每张图都要手动排除。
"""

from app.models import prompt as categories

# 通用负面词：绝大多数场景都该排除
_GENERIC_NEGATIVE = "文字，水印，logo，畸变，多余的手指，模糊，低清"

SEEDS: list[dict] = [
    {
        "title": "人物·氛围肖像",
        "category": categories.PORTRAIT,
        "description": "通用人像底稿：只改主体与光线，风格词已经调好。",
        "prompt_template": (
            "{{subject}}，{{light:柔和侧光}}，{{style:胶片质感}}，"
            "皮肤保留真实肌理，浅景深，高清细节，柔和色调"
        ),
        "negative_template": f"{_GENERIC_NEGATIVE}，过度磨皮，塑料感",
        "variables": [
            {
                "name": "subject",
                "label": "人物",
                "placeholder": "例如：一位穿白裙的年轻东亚女性，长发垂落",
                "options": [],
            },
            {
                "name": "light",
                "label": "光线",
                "placeholder": "柔和侧光",
                "options": ["柔和侧光", "逆光轮廓光", "伦勃朗光", "阴天漫射光"],
            },
            {
                "name": "style",
                "label": "风格",
                "placeholder": "胶片质感",
                "options": ["胶片质感", "清透日系", "复古港风", "商业棚拍"],
            },
        ],
        "default_ratio": "9:16",
        "default_count": 4,
    },
    {
        "title": "知识图谱·留白骨架",
        "category": categories.KNOWLEDGE_GRAPH,
        "description": "只画节点与连线的骨架，文字留白待补——模型写不准字，别指望它。",
        "prompt_template": (
            "{{topic}} 的知识图谱示意图，{{style:白板手绘}}，"
            "中心一个主节点，{{branches:5}} 个分支节点呈放射状排布，"
            "连线清晰，节点为留白的圆形与圆角矩形（内部不写任何文字），"
            "大量留白供后期添加文字，扁平配色，干净的浅色背景"
        ),
        "negative_template": f"{_GENERIC_NEGATIVE}，密集文字，杂乱连线，写实照片",
        "variables": [
            {
                "name": "topic",
                "label": "主题",
                "placeholder": "例如：机器学习知识体系",
                "options": [],
            },
            {
                "name": "branches",
                "label": "分支数",
                "placeholder": "5",
                "options": ["3", "4", "5", "6", "8"],
            },
            {
                "name": "style",
                "label": "风格",
                "placeholder": "白板手绘",
                "options": ["白板手绘", "扁平矢量", "极简几何", "低饱和插画"],
            },
        ],
        "default_ratio": "16:9",
        "default_count": 4,
    },
    {
        "title": "架构流程·分层框图",
        "category": categories.ARCHITECTURE,
        "description": "分层架构图骨架：区块留白、箭头走向清晰，文字后期补。",
        "prompt_template": (
            "{{system}} 的{{diagram:系统架构}}图，{{style:扁平矢量}}，"
            "自上而下分 {{layers:3}} 层，每层为留白的圆角矩形区块（内部不写文字），"
            "区块之间用清晰箭头表示调用方向，配色克制统一，大量留白，白色背景"
        ),
        "negative_template": f"{_GENERIC_NEGATIVE}，拥挤排版，手写体，3D 立体效果",
        "variables": [
            {
                "name": "system",
                "label": "系统",
                "placeholder": "例如：电商订单系统",
                "options": [],
            },
            {
                "name": "diagram",
                "label": "图类型",
                "placeholder": "系统架构",
                "options": ["系统架构", "部署拓扑", "数据流转", "业务流程"],
            },
            {
                "name": "layers",
                "label": "层数",
                "placeholder": "3",
                "options": ["2", "3", "4", "5"],
            },
            {
                "name": "style",
                "label": "风格",
                "placeholder": "扁平矢量",
                "options": ["扁平矢量", "白板手绘", "深色科技风", "低饱和插画"],
            },
        ],
        "default_ratio": "16:9",
        "default_count": 4,
    },
    {
        "title": "产品·电商主图",
        "category": categories.PRODUCT,
        "description": "商品主体 + 场景氛围，适合做详情页主图底稿。",
        "prompt_template": (
            "{{product}}，置于 {{scene:浅木色桌面}}，{{light:柔和自然光}}，"
            "产品摄影，主体清晰突出，浅景深，材质细节真实，高级感"
        ),
        "negative_template": f"{_GENERIC_NEGATIVE}，杂乱背景，强反光",
        "variables": [
            {
                "name": "product",
                "label": "商品",
                "placeholder": "例如：白色陶瓷马克杯",
                "options": [],
            },
            {
                "name": "scene",
                "label": "场景",
                "placeholder": "浅木色桌面",
                "options": ["浅木色桌面", "大理石台面", "亚麻布背景", "户外草地"],
            },
            {
                "name": "light",
                "label": "光线",
                "placeholder": "柔和自然光",
                "options": ["柔和自然光", "侧逆光", "影棚柔光箱", "清晨窗光"],
            },
        ],
        "default_ratio": "1:1",
        "default_count": 4,
    },
    {
        "title": "海报·留白版式",
        "category": categories.POSTER,
        "description": "中央留白的海报底稿，标题文字后期加。",
        "prompt_template": (
            "{{theme}} 主题海报，{{style:极简现代}}，"
            "画面上方三分之一与下方三分之一留白用于放置文字，"
            "主体集中于画面中部，配色克制，高级质感"
        ),
        "negative_template": f"{_GENERIC_NEGATIVE}，杂乱元素，过度装饰",
        "variables": [
            {
                "name": "theme",
                "label": "主题",
                "placeholder": "例如：春季新品发布",
                "options": [],
            },
            {
                "name": "style",
                "label": "风格",
                "placeholder": "极简现代",
                "options": ["极简现代", "国风雅致", "复古波普", "科技未来"],
            },
        ],
        "default_ratio": "3:4",
        "default_count": 4,
    },
    {
        "title": "插画·概念场景",
        "category": categories.ILLUSTRATION,
        "description": "氛围优先的概念插画，适合做封面或背景。",
        "prompt_template": (
            "{{scene}}，{{mood:静谧治愈}}，{{style:水彩插画}}，"
            "层次分明，构图完整，柔和光影，细腻笔触"
        ),
        "negative_template": f"{_GENERIC_NEGATIVE}，人物畸变，构图失衡",
        "variables": [
            {
                "name": "scene",
                "label": "场景",
                "placeholder": "例如：雨后古镇的小巷，青石板路泛着光",
                "options": [],
            },
            {
                "name": "mood",
                "label": "氛围",
                "placeholder": "静谧治愈",
                "options": ["静谧治愈", "寂寥苍茫", "温暖怀旧", "梦幻空灵"],
            },
            {
                "name": "style",
                "label": "风格",
                "placeholder": "水彩插画",
                "options": ["水彩插画", "厚涂油画", "扁平矢量", "国风工笔"],
            },
        ],
        "default_ratio": "16:9",
        "default_count": 4,
    },
]
