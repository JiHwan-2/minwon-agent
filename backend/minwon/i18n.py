"""다국어: 시민의 언어 감지와 정해진 안내문 번역.

지원 언어는 한국어 + 영어·중국어·베트남어 (베트남·중국은 경남 외국인 주민 국적 1·2위, 중국은 한국계 포함 —
행정안전부 2024 지방자치단체 외국인주민 현황. 영어는 그 밖의 외국인을 위한 공용어).
대화·민원 번역본은 Claude가 시민의 언어로 쓰고, 정해진 안내문(위기·긴급·다른 창구 등)은 여기 번역만 쓴다.
지원하지 않는 언어로 말하면 모든 안내를 영어로 한다.
"""

import re

LANGS = ("ko", "en", "zh", "vi")
LANG_NAMES = {"ko": "한국어", "en": "English", "zh": "中文", "vi": "Tiếng Việt"}
FALLBACK = "en"

_HANGUL = re.compile(r"[가-힣]")
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")
_VIET = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]")


def normalize(code: str | None) -> str:
    """'zh-CN'·'KO' 같은 표기를 두 글자 언어 코드로."""
    return (code or "").strip().lower().replace("_", "-").split("-")[0][:3]


def detect(text: str) -> str | None:
    """글자 모양으로 바로 알 수 있는 지원 언어만 판별한다 (AI 판단 전·실패 때 쓰는 보조).
    라틴 문자(영어 등)와 지원하지 않는 문자는 모름(None). 일본어는 한자가 섞여도 중국어로 보지 않는다."""
    if _HANGUL.search(text):
        return "ko"
    if _KANA.search(text):
        return None
    if _HAN.search(text):
        return "zh"
    if _VIET.search(text):
        return "vi"
    return None


def ui_lang(code: str | None) -> str:
    """대화·안내·화면에 쓸 언어: 지원 언어면 그대로, 아니면 영어 (모르면 한국어)."""
    code = normalize(code)
    if not code:
        return "ko"
    return code if code in LANGS else FALLBACK


def t(key: str, lang: str | None, **values) -> str:
    texts = TEXT[key]
    return texts.get(ui_lang(lang), texts["ko"]).format(**values)


def referral(code: str, lang: str | None, base: dict) -> dict:
    """다른 창구 안내 카드: 지식베이스(한국어) 위에 그 언어 번역을 덮는다."""
    lang = ui_lang(lang)
    return base | (REFERRALS[code].get(lang, {}) if lang != "ko" else {})


TEXT: dict[str, dict[str, str]] = {
    "crisis.notice": {
        "ko": "많이 힘드시다면 혼자 견디지 마세요. 자살예방 상담전화 109(24시간)에 전화하면 언제든 이야기를 들어 드려요. 지금 위험한 상황이라면 112·119에 바로 연락해 주세요.",
        "vi": "Nếu bạn đang gặp nhiều khó khăn, xin đừng chịu đựng một mình. Bạn có thể gọi đường dây tư vấn phòng chống tự tử 109 (24 giờ) bất cứ lúc nào để được lắng nghe. Nếu bạn đang gặp nguy hiểm, hãy gọi ngay 112 hoặc 119.",
        "zh": "如果您现在很难受，请不要一个人承受。您可以随时拨打自杀预防咨询电话109（24小时），会有人倾听您的心声。如果现在情况危险，请立即拨打112或119。",
        "en": "If you are going through a hard time, please don't carry it alone. You can call the suicide prevention hotline 109 (24 hours) anytime to talk to someone. If you are in danger right now, call 112 or 119 immediately.",
    },
    "crisis.reply.new": {
        "ko": "말씀해 주셔서 고마워요. 위의 상담전화는 언제든 연결돼요. 생활 속 불편한 일이 생기면 그때 편하게 말씀해 주세요.",
        "vi": "Cảm ơn bạn đã chia sẻ. Đường dây tư vấn ở trên luôn sẵn sàng bất cứ lúc nào. Khi gặp điều bất tiện trong cuộc sống, bạn cứ thoải mái nói với tôi nhé.",
        "zh": "谢谢您告诉我。上面的咨询电话随时都可以接通。以后如果生活中遇到不便，欢迎随时告诉我。",
        "en": "Thank you for telling me. The hotline above is available anytime. If you ever have an everyday problem to report, feel free to tell me then.",
    },
    "crisis.reply.paused": {
        "ko": "말씀해 주셔서 고마워요. 위의 상담전화는 언제든 연결돼요. 하던 민원은 그대로 두었으니 원하실 때 이어서 말씀해 주세요.",
        "vi": "Cảm ơn bạn đã chia sẻ. Đường dây tư vấn ở trên luôn sẵn sàng. Tôi đã giữ nguyên đơn kiến nghị đang làm dở, khi nào sẵn sàng bạn có thể tiếp tục.",
        "zh": "谢谢您告诉我。上面的咨询电话随时都可以接通。正在办理的投诉已为您保留，您准备好后可以随时继续。",
        "en": "Thank you for telling me. The hotline above is available anytime. I've kept your request as it is, so you can continue whenever you're ready.",
    },
    "off_topic.asking": {
        "ko": "질문에 대한 답으로 보기 어려워서 그대로 두었어요. 아래 질문에 이어서 답해 주세요. 모르는 건 '모름'이라고 적어도 돼요.",
        "vi": "Câu này có vẻ không phải là câu trả lời cho câu hỏi nên tôi giữ nguyên. Vui lòng trả lời tiếp các câu hỏi bên dưới. Nếu không biết, bạn có thể ghi 'không biết'.",
        "zh": "这似乎不是对问题的回答，所以我先保持不变。请继续回答下面的问题。不知道的话，写“不知道”也可以。",
        "en": "That doesn't seem to answer the question, so I've left things as they are. Please answer the questions below. If you don't know, just say so.",
    },
    "off_topic.ready": {
        "ko": "민원 초안은 그대로 두었어요. 고칠 점이 있으면 '더 짧게'처럼 말씀해 주시고, 다른 불편이 있으면 그 내용을 말씀해 주세요.",
        "vi": "Tôi đã giữ nguyên bản nháp. Nếu muốn sửa, hãy nói như 'viết ngắn hơn'. Nếu có điều bất tiện khác, hãy cho tôi biết nội dung.",
        "zh": "草稿保持不变。如需修改，请告诉我，例如“写短一点”；如果有其他不便，也请直接告诉我。",
        "en": "I've left the draft as it is. If you'd like changes, tell me something like 'make it shorter'. If you have a different problem, just describe it.",
    },
    "reply.unclear": {
        "ko": "어떤 점이 불편하신지 조금만 더 알려 주세요. 예를 들어 '집 앞 가로등이 며칠째 꺼져 있어요'처럼 말씀해 주시면 돼요.",
        "vi": "Bạn có thể nói rõ hơn điều gì đang gây bất tiện không? Ví dụ: 'Đèn đường trước nhà tôi đã tắt mấy ngày nay.'",
        "zh": "能再具体说说是哪里不方便吗？例如：“我家门前的路灯已经好几天不亮了。”",
        "en": "Could you tell me a little more about what is bothering you? For example: 'The streetlight in front of my house has been off for days.'",
    },
    "reply.not_complaint": {
        "ko": "저는 생활 속 불편을 민원으로 정리해 드리는 도우미예요. '학교 앞 횡단보도가 위험해요'처럼 불편했던 일을 말씀해 주세요.",
        "vi": "Tôi là trợ lý giúp bạn soạn đơn kiến nghị về những bất tiện trong cuộc sống và tìm đúng cơ quan phụ trách. Hãy kể cho tôi điều bất tiện, ví dụ: 'Lối qua đường trước trường học rất nguy hiểm.'",
        "zh": "我是帮您把生活中的不便整理成投诉、并找到负责机关的助手。请告诉我您遇到的不便，例如：“学校门前的人行横道很危险。”",
        "en": "I'm an assistant that turns everyday problems into complaints for the right government office. Please tell me about a problem, for example: 'The crosswalk in front of the school is dangerous.'",
    },
    "referral.reply": {
        "ko": "말씀하신 일은 '{label}'에 해당해서, 시·군·구청 민원보다 {agency}에서 도와줘요. {first}",
        "vi": "Việc bạn nói thuộc nhóm '{label}', nên {agency} sẽ hỗ trợ phù hợp hơn ủy ban thành phố/quận. {first}",
        "zh": "您说的情况属于“{label}”，比起市·郡·区厅，{agency}更能帮到您。{first}",
        "en": "This falls under '{label}', so {agency} can help you better than a city or district office. {first}",
    },
    "location.vague": {
        "ko": "말씀하신 '{place}'만으로는 정확한 곳을 찾기 어려워요. 장소 이름(예: ○○초등학교), 동 이름, 또는 도로명 주소를 알려 주세요.",
        "vi": "Chỉ với '{place}' thì khó xác định chính xác địa điểm. Vui lòng cho biết tên địa điểm (ví dụ: Trường tiểu học ○○), tên phường (dong) hoặc địa chỉ đường.",
        "zh": "仅凭“{place}”很难找到准确的位置。请告诉我地点名称（例如：○○小学）、洞名或道路名地址。",
        "en": "It's hard to find the exact spot from '{place}' alone. Please tell me a place name (e.g., ○○ Elementary School), the neighborhood (dong), or the street address.",
    },
    "location.choose": {
        "ko": "'{query}'에 해당하는 곳이 {count}곳 있어요. 어느 곳인가요? 번호를 고르거나, 더 정확한 장소 이름·주소를 알려 주세요.",
        "vi": "Có {count} địa điểm khớp với '{query}'. Là nơi nào? Hãy chọn số hoặc cho biết tên địa điểm/địa chỉ chính xác hơn.",
        "zh": "与“{query}”相符的地点有{count}处。是哪一处？请选择编号，或告诉我更准确的地点名称或地址。",
        "en": "There are {count} places matching '{query}'. Which one is it? Pick a number, or tell me a more exact place name or address.",
    },
    "cancelled": {
        "ko": "처리를 멈췄어요. 내용을 고쳐서 다시 보내 주세요.",
        "vi": "Đã dừng xử lý. Vui lòng sửa nội dung và gửi lại.",
        "zh": "已停止处理。请修改内容后重新发送。",
        "en": "Stopped. Please edit your message and send it again.",
    },
    "error.agent": {
        "ko": "처리 중 문제가 생겼어요. 같은 내용으로 다시 보내 주세요. ({error})",
        "vi": "Đã xảy ra sự cố khi xử lý. Vui lòng gửi lại nội dung tương tự. ({error})",
        "zh": "处理时出现问题。请重新发送相同的内容。（{error}）",
        "en": "Something went wrong. Please send the same message again. ({error})",
    },
    "error.busy": {
        "ko": "이전 처리가 끝나지 않았어요. '새 민원'으로 다시 시작해 주세요.",
        "vi": "Yêu cầu trước chưa xử lý xong. Vui lòng bắt đầu lại bằng nút 'Yêu cầu mới'.",
        "zh": "上一个处理尚未结束。请点击“新的投诉”重新开始。",
        "en": "The previous request isn't finished. Please start again with 'New request'.",
    },
}

# 다른 창구 안내 카드 번역 (원문·번호·주소는 knowledge/agencies.json의 referrals). 기관 이름은 한국어 원문을 괄호로 남겨 찾을 수 있게 한다.
REFERRALS: dict[str, dict[str, dict[str, str]]] = {
    "consumer": {
        "vi": {"label": "Thiệt hại của người tiêu dùng", "agency": "Trung tâm tư vấn người tiêu dùng 1372 (1372 소비자상담센터)",
               "operator": "Do Ủy ban Thương mại Công bằng vận hành, Cơ quan Người tiêu dùng Hàn Quốc hỗ trợ", "hours": "Ngày thường 09:00–18:00",
               "first": "Trước tiên hãy yêu cầu người bán hoặc trung tâm chăm sóc khách hàng của công ty giao hàng. Nếu không giải quyết được, hãy đăng ký tư vấn. Nếu tư vấn vẫn không giải quyết được, bạn có thể yêu cầu Cơ quan Người tiêu dùng Hàn Quốc hỗ trợ khắc phục thiệt hại."},
        "zh": {"label": "消费者权益受损", "agency": "1372消费者咨询中心（1372 소비자상담센터）",
               "operator": "公平交易委员会运营，韩国消费者院支持", "hours": "工作日 09:00~18:00",
               "first": "请先向卖家或快递公司客服提出要求；如果无法解决，再申请咨询。咨询后仍无法解决的，可以向韩国消费者院申请损害救济。"},
        "en": {"label": "Consumer damage", "agency": "1372 Consumer Counseling Center (1372 소비자상담센터)",
               "operator": "Run by the Fair Trade Commission, supported by the Korea Consumer Agency", "hours": "Weekdays 09:00–18:00",
               "first": "First ask the seller or the delivery company's customer center. If that doesn't solve it, apply for counseling. If counseling doesn't resolve it, you can request damage relief from the Korea Consumer Agency."},
    },
    "labor": {
        "vi": {"label": "Nợ lương và các vấn đề nơi làm việc", "agency": "Trung tâm tư vấn khách hàng Bộ Việc làm và Lao động (고용노동부 고객상담센터)",
               "operator": "Bộ Việc làm và Lao động", "hours": "Ngày thường 09:00–18:00",
               "first": "Sau khi được tư vấn, bạn có thể nộp đơn khiếu nại trên Cổng thông tin Lao động (노동포털) hoặc đến Sở Việc làm và Lao động khu vực."},
        "zh": {"label": "拖欠工资等职场问题", "agency": "雇佣劳动部客户咨询中心（고용노동부 고객상담센터）",
               "operator": "雇佣劳动部", "hours": "工作日 09:00~18:00",
               "first": "咨询后，可以在劳动门户网站（노동포털）提交陈情书，或前往管辖地区的地方雇佣劳动厅。"},
        "en": {"label": "Unpaid wages and workplace problems", "agency": "Ministry of Employment and Labor Customer Center (고용노동부 고객상담센터)",
               "operator": "Ministry of Employment and Labor", "hours": "Weekdays 09:00–18:00",
               "first": "After counseling, you can file a petition on the Labor Portal (노동포털) or visit your regional employment and labor office."},
    },
    "crime": {
        "vi": {"label": "Lừa đảo và các tội phạm khác", "agency": "Cảnh sát (Hệ thống báo cáo tội phạm mạng / đồn cảnh sát gần nhất, 경찰서)",
               "operator": "Cơ quan Cảnh sát Quốc gia Hàn Quốc", "phone": "112 (khi khẩn cấp)", "hours": "Báo cáo trực tuyến 24 giờ",
               "first": "Với lừa đảo qua mạng, hãy báo cáo trước trên Hệ thống báo cáo tội phạm mạng rồi đến đồn cảnh sát để nộp chính thức. Đừng xóa tin nhắn và lịch sử chuyển tiền, hãy chụp màn hình lại."},
        "zh": {"label": "诈骗等犯罪受害", "agency": "警察（网络犯罪举报系统·附近的警察署 경찰서）",
               "operator": "韩国警察厅", "phone": "112（紧急时）", "hours": "网上举报24小时",
               "first": "网络诈骗请先在网络犯罪举报系统举报，再到警察署正式立案。聊天记录和转账记录不要删除，请截图保存。"},
        "en": {"label": "Fraud and other crimes", "agency": "Police (Cyber Crime Reporting System / nearest police station, 경찰서)",
               "operator": "Korean National Police Agency", "phone": "112 (in an emergency)", "hours": "Online reports 24 hours",
               "first": "For online fraud, report it first on the Cyber Crime Reporting System, then file it officially at a police station. Don't delete chats or payment records—take screenshots."},
    },
    "legal": {
        "vi": {"label": "Tranh chấp pháp lý giữa cá nhân", "agency": "Tư vấn pháp lý 132 của Tổng công ty Trợ giúp Pháp lý Hàn Quốc (대한법률구조공단)",
               "operator": "Tổng công ty Trợ giúp Pháp lý Hàn Quốc", "hours": "Ngày thường 09:00–18:00 (trừ giờ nghỉ trưa)",
               "first": "Cơ quan hành chính không thể phân xử tranh chấp giữa các cá nhân, vì vậy tốt nhất là nhận tư vấn pháp lý miễn phí để biết cách giải quyết."},
        "zh": {"label": "个人之间的法律纠纷", "agency": "大韩法律救助公团132法律咨询（대한법률구조공단）",
               "operator": "大韩法律救助公团", "hours": "工作日 09:00~18:00（午休除外）",
               "first": "个人之间的纠纷行政机关无法代为裁决，建议通过免费法律咨询了解解决办法。"},
        "en": {"label": "Legal disputes between individuals", "agency": "Korea Legal Aid Corporation 132 legal counseling (대한법률구조공단)",
               "operator": "Korea Legal Aid Corporation", "hours": "Weekdays 09:00–18:00 (except lunch)",
               "first": "Government offices can't settle disputes between individuals for you, so free legal counseling is the best way to learn your options."},
    },
}
