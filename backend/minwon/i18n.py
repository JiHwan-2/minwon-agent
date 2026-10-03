"""다국어: 시민의 언어 감지와 정해진 안내문 번역.

번역해 둔 언어는 한국어 + 경남 외국인 주민 상위 5개 국적 언어(베트남어·중국어·태국어·인도네시아어·우즈베크어,
행정안전부 2024 지방자치단체 외국인주민 현황) + 영어·일본어. Claude가 쓰는 대화·민원 글은 어떤 언어든 시민의 언어로 쓰고,
정해진 안내문(위기·긴급·다른 창구 등)은 여기 번역만 쓴다. 번역해 두지 않은 언어는 영어 안내문을 쓴다.
"""

import re

LANGS = ("ko", "vi", "zh", "th", "id", "uz", "en", "ja")
LANG_NAMES = {
    "ko": "한국어", "vi": "Tiếng Việt", "zh": "中文", "th": "ไทย", "id": "Bahasa Indonesia",
    "uz": "O'zbekcha", "en": "English", "ja": "日本語",
}
FALLBACK = "en"

_HANGUL = re.compile(r"[가-힣]")
_KANA = re.compile(r"[぀-ヿ]")
_THAI = re.compile(r"[฀-๿]")
_HAN = re.compile(r"[一-鿿]")
_VIET = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]")


def normalize(code: str | None) -> str:
    """'zh-CN'·'KO' 같은 표기를 두 글자 언어 코드로."""
    return (code or "").strip().lower().replace("_", "-").split("-")[0][:3]


def detect(text: str) -> str | None:
    """글자 모양으로 바로 알 수 있는 언어만 판별한다 (AI 판단 전·실패 때 쓰는 보조). 라틴 문자는 모름(None)."""
    if _HANGUL.search(text):
        return "ko"
    if _KANA.search(text):
        return "ja"
    if _THAI.search(text):
        return "th"
    if _HAN.search(text):
        return "zh"
    if _VIET.search(text):
        return "vi"
    return None


def ui_lang(code: str | None) -> str:
    """정해진 안내문·화면에 쓸 언어: 번역해 둔 언어면 그대로, 아니면 영어 (모르면 한국어)."""
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
        "th": "หากคุณกำลังรู้สึกทุกข์ใจมาก อย่าเผชิญกับมันเพียงลำพัง คุณโทรสายด่วนป้องกันการฆ่าตัวตาย 109 (24 ชั่วโมง) ได้ตลอดเวลา หากตอนนี้อยู่ในสถานการณ์อันตราย โปรดโทร 112 หรือ 119 ทันที",
        "id": "Jika Anda sedang mengalami masa yang sangat berat, jangan menanggungnya sendirian. Anda dapat menelepon layanan konseling pencegahan bunuh diri 109 (24 jam) kapan saja. Jika Anda dalam bahaya sekarang, segera hubungi 112 atau 119.",
        "uz": "Agar sizga juda og'ir bo'layotgan bo'lsa, buni yolg'iz ko'tarmang. O'z joniga qasd qilishning oldini olish ishonch telefoni 109 (24 soat) ga istalgan vaqtda qo'ng'iroq qilishingiz mumkin. Hozir xavfli vaziyatda bo'lsangiz, darhol 112 yoki 119 ga qo'ng'iroq qiling.",
        "en": "If you are going through a hard time, please don't carry it alone. You can call the suicide prevention hotline 109 (24 hours) anytime to talk to someone. If you are in danger right now, call 112 or 119 immediately.",
        "ja": "とてもつらい状況でしたら、一人で抱え込まないでください。自殺予防相談電話109（24時間）にはいつでも電話でき、お話を聞いてもらえます。今危険な状況にある場合は、すぐに112または119に連絡してください。",
    },
    "crisis.reply.new": {
        "ko": "말씀해 주셔서 고마워요. 위의 상담전화는 언제든 연결돼요. 생활 속 불편한 일이 생기면 그때 편하게 말씀해 주세요.",
        "vi": "Cảm ơn bạn đã chia sẻ. Đường dây tư vấn ở trên luôn sẵn sàng bất cứ lúc nào. Khi gặp điều bất tiện trong cuộc sống, bạn cứ thoải mái nói với tôi nhé.",
        "zh": "谢谢您告诉我。上面的咨询电话随时都可以接通。以后如果生活中遇到不便，欢迎随时告诉我。",
        "th": "ขอบคุณที่เล่าให้ฟังนะ สายด่วนข้างต้นติดต่อได้ตลอดเวลา หากมีเรื่องไม่สะดวกในชีวิตประจำวัน บอกเราได้เสมอ",
        "id": "Terima kasih sudah bercerita. Layanan telepon di atas bisa dihubungi kapan saja. Jika nanti ada ketidaknyamanan dalam kehidupan sehari-hari, silakan ceritakan kepada saya.",
        "uz": "Aytganingiz uchun rahmat. Yuqoridagi ishonch telefoni istalgan vaqtda ishlaydi. Kundalik hayotda biror noqulaylik bo'lsa, bemalol menga ayting.",
        "en": "Thank you for telling me. The hotline above is available anytime. If you ever have an everyday problem to report, feel free to tell me then.",
        "ja": "話してくださってありがとうございます。上の相談電話はいつでもつながります。生活の中で困ったことがあれば、そのときは気軽に話してください。",
    },
    "crisis.reply.paused": {
        "ko": "말씀해 주셔서 고마워요. 위의 상담전화는 언제든 연결돼요. 하던 민원은 그대로 두었으니 원하실 때 이어서 말씀해 주세요.",
        "vi": "Cảm ơn bạn đã chia sẻ. Đường dây tư vấn ở trên luôn sẵn sàng. Tôi đã giữ nguyên đơn kiến nghị đang làm dở, khi nào sẵn sàng bạn có thể tiếp tục.",
        "zh": "谢谢您告诉我。上面的咨询电话随时都可以接通。正在办理的投诉已为您保留，您准备好后可以随时继续。",
        "th": "ขอบคุณที่เล่าให้ฟังนะ สายด่วนข้างต้นติดต่อได้ตลอดเวลา เรื่องร้องเรียนที่ทำค้างไว้ยังเก็บไว้เหมือนเดิม พร้อมเมื่อไหร่ค่อยทำต่อได้",
        "id": "Terima kasih sudah bercerita. Layanan telepon di atas bisa dihubungi kapan saja. Pengaduan yang sedang dibuat tetap saya simpan, silakan lanjutkan kapan pun Anda siap.",
        "uz": "Aytganingiz uchun rahmat. Yuqoridagi ishonch telefoni istalgan vaqtda ishlaydi. Boshlagan murojaatingiz saqlab qo'yildi, tayyor bo'lganingizda davom ettirishingiz mumkin.",
        "en": "Thank you for telling me. The hotline above is available anytime. I've kept your request as it is, so you can continue whenever you're ready.",
        "ja": "話してくださってありがとうございます。上の相談電話はいつでもつながります。進めていた苦情はそのまま残してあるので、準備ができたらいつでも続けてください。",
    },
    "off_topic.asking": {
        "ko": "질문에 대한 답으로 보기 어려워서 그대로 두었어요. 아래 질문에 이어서 답해 주세요. 모르는 건 '모름'이라고 적어도 돼요.",
        "vi": "Câu này có vẻ không phải là câu trả lời cho câu hỏi nên tôi giữ nguyên. Vui lòng trả lời tiếp các câu hỏi bên dưới. Nếu không biết, bạn có thể ghi 'không biết'.",
        "zh": "这似乎不是对问题的回答，所以我先保持不变。请继续回答下面的问题。不知道的话，写“不知道”也可以。",
        "th": "ดูเหมือนไม่ใช่คำตอบของคำถาม จึงยังไม่ได้ดำเนินการต่อ กรุณาตอบคำถามด้านล่าง ถ้าไม่ทราบ พิมพ์ว่า 'ไม่ทราบ' ได้",
        "id": "Itu sepertinya bukan jawaban atas pertanyaan, jadi saya biarkan seperti semula. Silakan jawab pertanyaan di bawah ini. Jika tidak tahu, cukup tulis 'tidak tahu'.",
        "uz": "Bu savolga javobga o'xshamadi, shuning uchun hech narsani o'zgartirmadim. Iltimos, quyidagi savollarga javob bering. Bilmasangiz, 'bilmayman' deb yozishingiz mumkin.",
        "en": "That doesn't seem to answer the question, so I've left things as they are. Please answer the questions below. If you don't know, just say so.",
        "ja": "質問への答えではないようなので、そのままにしています。下の質問に続けて答えてください。わからない場合は「わからない」と書いても大丈夫です。",
    },
    "off_topic.ready": {
        "ko": "민원 초안은 그대로 두었어요. 고칠 점이 있으면 '더 짧게'처럼 말씀해 주시고, 다른 불편이 있으면 그 내용을 말씀해 주세요.",
        "vi": "Tôi đã giữ nguyên bản nháp. Nếu muốn sửa, hãy nói như 'viết ngắn hơn'. Nếu có điều bất tiện khác, hãy cho tôi biết nội dung.",
        "zh": "草稿保持不变。如需修改，请告诉我，例如“写短一点”；如果有其他不便，也请直接告诉我。",
        "th": "ร่างยังคงเดิม ถ้าต้องการแก้ไข บอกได้ เช่น 'เขียนให้สั้นลง' และถ้ามีเรื่องไม่สะดวกอื่น ก็เล่าได้เลย",
        "id": "Draf tetap seperti semula. Jika ingin diubah, sampaikan misalnya 'buat lebih singkat'. Jika ada masalah lain, ceritakan saja.",
        "uz": "Qoralama o'zgarishsiz qoldi. O'zgartirish kerak bo'lsa, masalan 'qisqaroq yozing' deb ayting. Boshqa muammo bo'lsa, uni tasvirlab bering.",
        "en": "I've left the draft as it is. If you'd like changes, tell me something like 'make it shorter'. If you have a different problem, just describe it.",
        "ja": "下書きはそのままにしています。直したい点があれば「もっと短く」のように伝えてください。別の困りごとがあれば、その内容を話してください。",
    },
    "reply.unclear": {
        "ko": "어떤 점이 불편하신지 조금만 더 알려 주세요. 예를 들어 '집 앞 가로등이 며칠째 꺼져 있어요'처럼 말씀해 주시면 돼요.",
        "vi": "Bạn có thể nói rõ hơn điều gì đang gây bất tiện không? Ví dụ: 'Đèn đường trước nhà tôi đã tắt mấy ngày nay.'",
        "zh": "能再具体说说是哪里不方便吗？例如：“我家门前的路灯已经好几天不亮了。”",
        "th": "ช่วยเล่าเพิ่มอีกนิดได้ไหมว่าไม่สะดวกเรื่องอะไร เช่น 'ไฟถนนหน้าบ้านดับมาหลายวันแล้ว'",
        "id": "Bisa ceritakan sedikit lebih jelas apa yang mengganggu Anda? Misalnya: 'Lampu jalan di depan rumah saya sudah mati beberapa hari.'",
        "uz": "Sizni nima bezovta qilayotganini biroz batafsilroq ayta olasizmi? Masalan: 'Uyim oldidagi ko'cha chirog'i bir necha kundan beri yonmayapti.'",
        "en": "Could you tell me a little more about what is bothering you? For example: 'The streetlight in front of my house has been off for days.'",
        "ja": "どんなことでお困りか、もう少し教えていただけますか。例えば「家の前の街灯が何日も消えたままです」のように話してください。",
    },
    "reply.not_complaint": {
        "ko": "저는 생활 속 불편을 민원으로 정리해 드리는 도우미예요. '학교 앞 횡단보도가 위험해요'처럼 불편했던 일을 말씀해 주세요.",
        "vi": "Tôi là trợ lý giúp bạn soạn đơn kiến nghị về những bất tiện trong cuộc sống và tìm đúng cơ quan phụ trách. Hãy kể cho tôi điều bất tiện, ví dụ: 'Lối qua đường trước trường học rất nguy hiểm.'",
        "zh": "我是帮您把生活中的不便整理成投诉、并找到负责机关的助手。请告诉我您遇到的不便，例如：“学校门前的人行横道很危险。”",
        "th": "ฉันเป็นผู้ช่วยเรียบเรียงเรื่องไม่สะดวกในชีวิตประจำวันเป็นเรื่องร้องเรียนถึงหน่วยงานที่รับผิดชอบ เล่าเรื่องที่ไม่สะดวกให้ฟังได้เลย เช่น 'ทางม้าลายหน้าโรงเรียนอันตรายมาก'",
        "id": "Saya asisten yang membantu menyusun pengaduan tentang ketidaknyamanan sehari-hari dan menemukan instansi yang tepat. Ceritakan masalah Anda, misalnya: 'Penyeberangan di depan sekolah berbahaya.'",
        "uz": "Men kundalik noqulayliklarni tegishli davlat idorasiga murojaat qilib tayyorlab beradigan yordamchiman. Muammoingizni ayting, masalan: 'Maktab oldidagi piyodalar o'tish joyi xavfli.'",
        "en": "I'm an assistant that turns everyday problems into complaints for the right government office. Please tell me about a problem, for example: 'The crosswalk in front of the school is dangerous.'",
        "ja": "私は、生活の中の困りごとを担当機関への苦情としてまとめるお手伝いをするアシスタントです。例えば「学校前の横断歩道が危ない」のように、困っていることを話してください。",
    },
    "referral.reply": {
        "ko": "말씀하신 일은 '{label}'에 해당해서, 시·군·구청 민원보다 {agency}에서 도와줘요. {first}",
        "vi": "Việc bạn nói thuộc nhóm '{label}', nên {agency} sẽ hỗ trợ phù hợp hơn ủy ban thành phố/quận. {first}",
        "zh": "您说的情况属于“{label}”，比起市·郡·区厅，{agency}更能帮到您。{first}",
        "th": "เรื่องที่เล่ามาเป็น '{label}' ดังนั้น {agency} จะช่วยได้ตรงกว่าสำนักงานเมือง/เขต {first}",
        "id": "Masalah ini termasuk '{label}', jadi {agency} lebih tepat membantu daripada kantor kota/kabupaten. {first}",
        "uz": "Aytgan holatingiz '{label}' toifasiga kiradi, shuning uchun shahar yoki tuman hokimligidan ko'ra {agency} yaxshiroq yordam beradi. {first}",
        "en": "This falls under '{label}', so {agency} can help you better than a city or district office. {first}",
        "ja": "お話の件は「{label}」にあたるため、市・郡・区役所より{agency}のほうが適切に対応してくれます。{first}",
    },
    "location.vague": {
        "ko": "말씀하신 '{place}'만으로는 정확한 곳을 찾기 어려워요. 장소 이름(예: ○○초등학교), 동 이름, 또는 도로명 주소를 알려 주세요.",
        "vi": "Chỉ với '{place}' thì khó xác định chính xác địa điểm. Vui lòng cho biết tên địa điểm (ví dụ: Trường tiểu học ○○), tên phường (dong) hoặc địa chỉ đường.",
        "zh": "仅凭“{place}”很难找到准确的位置。请告诉我地点名称（例如：○○小学）、洞名或道路名地址。",
        "th": "จาก '{place}' อย่างเดียวหาตำแหน่งที่แน่นอนได้ยาก กรุณาบอกชื่อสถานที่ (เช่น โรงเรียนประถม ○○) ชื่อย่าน (ทง) หรือที่อยู่ตามชื่อถนน",
        "id": "Sulit menemukan lokasi tepatnya hanya dari '{place}'. Mohon sebutkan nama tempat (mis. SD ○○), nama kelurahan (dong), atau alamat jalan.",
        "uz": "Faqat '{place}' orqali aniq joyni topish qiyin. Iltimos, joy nomi (masalan, ○○ boshlang'ich maktabi), mahalla (dong) nomi yoki ko'cha manzilini ayting.",
        "en": "It's hard to find the exact spot from '{place}' alone. Please tell me a place name (e.g., ○○ Elementary School), the neighborhood (dong), or the street address.",
        "ja": "「{place}」だけでは正確な場所を見つけるのが難しいです。場所の名前（例：○○小学校）、洞の名前、または道路名住所を教えてください。",
    },
    "location.choose": {
        "ko": "'{query}'에 해당하는 곳이 {count}곳 있어요. 어느 곳인가요? 번호를 고르거나, 더 정확한 장소 이름·주소를 알려 주세요.",
        "vi": "Có {count} địa điểm khớp với '{query}'. Là nơi nào? Hãy chọn số hoặc cho biết tên địa điểm/địa chỉ chính xác hơn.",
        "zh": "与“{query}”相符的地点有{count}处。是哪一处？请选择编号，或告诉我更准确的地点名称或地址。",
        "th": "มีสถานที่ที่ตรงกับ '{query}' อยู่ {count} แห่ง เป็นที่ไหน? เลือกหมายเลข หรือบอกชื่อสถานที่/ที่อยู่ที่ชัดเจนกว่านี้",
        "id": "Ada {count} tempat yang cocok dengan '{query}'. Yang mana? Pilih nomornya, atau sebutkan nama tempat atau alamat yang lebih tepat.",
        "uz": "'{query}' ga mos {count} ta joy bor. Qaysi biri? Raqamni tanlang yoki aniqroq joy nomi yoki manzilni ayting.",
        "en": "There are {count} places matching '{query}'. Which one is it? Pick a number, or tell me a more exact place name or address.",
        "ja": "「{query}」に当てはまる場所が{count}か所あります。どこですか？番号を選ぶか、もっと正確な場所の名前・住所を教えてください。",
    },
    "cancelled": {
        "ko": "처리를 멈췄어요. 내용을 고쳐서 다시 보내 주세요.",
        "vi": "Đã dừng xử lý. Vui lòng sửa nội dung và gửi lại.",
        "zh": "已停止处理。请修改内容后重新发送。",
        "th": "หยุดการดำเนินการแล้ว กรุณาแก้ไขข้อความแล้วส่งใหม่อีกครั้ง",
        "id": "Proses dihentikan. Silakan ubah isinya lalu kirim lagi.",
        "uz": "Jarayon to'xtatildi. Iltimos, matnni tuzatib, qayta yuboring.",
        "en": "Stopped. Please edit your message and send it again.",
        "ja": "処理を止めました。内容を直してもう一度送ってください。",
    },
    "error.agent": {
        "ko": "처리 중 문제가 생겼어요. 같은 내용으로 다시 보내 주세요. ({error})",
        "vi": "Đã xảy ra sự cố khi xử lý. Vui lòng gửi lại nội dung tương tự. ({error})",
        "zh": "处理时出现问题。请重新发送相同的内容。（{error}）",
        "th": "เกิดปัญหาระหว่างดำเนินการ กรุณาส่งข้อความเดิมอีกครั้ง ({error})",
        "id": "Terjadi masalah saat memproses. Silakan kirim ulang pesan yang sama. ({error})",
        "uz": "Ishlov berishda muammo yuz berdi. Iltimos, xuddi shu matnni qayta yuboring. ({error})",
        "en": "Something went wrong. Please send the same message again. ({error})",
        "ja": "処理中に問題が起きました。同じ内容をもう一度送ってください。（{error}）",
    },
    "error.busy": {
        "ko": "이전 처리가 끝나지 않았어요. '새 민원'으로 다시 시작해 주세요.",
        "vi": "Yêu cầu trước chưa xử lý xong. Vui lòng bắt đầu lại bằng nút 'Yêu cầu mới'.",
        "zh": "上一个处理尚未结束。请点击“新的投诉”重新开始。",
        "th": "การดำเนินการก่อนหน้ายังไม่เสร็จ กรุณากด 'เริ่มเรื่องใหม่' เพื่อเริ่มใหม่",
        "id": "Proses sebelumnya belum selesai. Silakan mulai lagi dengan 'Pengaduan baru'.",
        "uz": "Oldingi jarayon tugamadi. Iltimos, 'Yangi murojaat' tugmasi bilan qaytadan boshlang.",
        "en": "The previous request isn't finished. Please start again with 'New request'.",
        "ja": "前の処理が終わっていません。「新しく始める」から始め直してください。",
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
        "th": {"label": "ความเสียหายของผู้บริโภค", "agency": "ศูนย์ให้คำปรึกษาผู้บริโภค 1372 (1372 소비자상담센터)",
               "operator": "ดำเนินการโดยคณะกรรมการการค้าที่เป็นธรรม สนับสนุนโดยสำนักงานผู้บริโภคเกาหลี", "hours": "วันธรรมดา 09:00–18:00",
               "first": "ก่อนอื่นให้ติดต่อผู้ขายหรือศูนย์บริการลูกค้าของบริษัทขนส่ง ถ้ายังแก้ไม่ได้ให้ขอรับคำปรึกษา หากปรึกษาแล้วยังไม่ได้รับการแก้ไข สามารถยื่นขอเยียวยาความเสียหายต่อสำนักงานผู้บริโภคเกาหลีได้"},
        "id": {"label": "Kerugian konsumen", "agency": "Pusat Konsultasi Konsumen 1372 (1372 소비자상담센터)",
               "operator": "Dikelola Komisi Perdagangan Adil, didukung Badan Konsumen Korea", "hours": "Hari kerja 09.00–18.00",
               "first": "Mintalah terlebih dahulu kepada penjual atau layanan pelanggan perusahaan pengiriman. Jika tidak selesai, ajukan konsultasi. Jika konsultasi pun tidak menyelesaikan masalah, Anda bisa mengajukan pemulihan kerugian ke Badan Konsumen Korea."},
        "uz": {"label": "Iste'molchi zarari", "agency": "1372 Iste'molchilar maslahat markazi (1372 소비자상담센터)",
               "operator": "Adolatli savdo komissiyasi boshqaradi, Koreya iste'molchilar agentligi qo'llab-quvvatlaydi", "hours": "Ish kunlari 09:00–18:00",
               "first": "Avval sotuvchi yoki yetkazib berish kompaniyasining mijozlar xizmatiga murojaat qiling. Hal bo'lmasa, maslahatga ariza bering. Maslahatdan keyin ham hal bo'lmasa, Koreya iste'molchilar agentligiga zararni qoplash bo'yicha ariza berishingiz mumkin."},
        "en": {"label": "Consumer damage", "agency": "1372 Consumer Counseling Center (1372 소비자상담센터)",
               "operator": "Run by the Fair Trade Commission, supported by the Korea Consumer Agency", "hours": "Weekdays 09:00–18:00",
               "first": "First ask the seller or the delivery company's customer center. If that doesn't solve it, apply for counseling. If counseling doesn't resolve it, you can request damage relief from the Korea Consumer Agency."},
        "ja": {"label": "消費者被害", "agency": "1372消費者相談センター（1372 소비자상담센터）",
               "operator": "公正取引委員会が運営、韓国消費者院が支援", "hours": "平日 09:00〜18:00",
               "first": "まず販売者や宅配会社のカスタマーセンターに求めてください。解決しなければ相談を申し込みましょう。相談でも解決しない場合は、韓国消費者院に被害救済を申請できます。"},
    },
    "labor": {
        "vi": {"label": "Nợ lương và các vấn đề nơi làm việc", "agency": "Trung tâm tư vấn khách hàng Bộ Việc làm và Lao động (고용노동부 고객상담센터)",
               "operator": "Bộ Việc làm và Lao động", "hours": "Ngày thường 09:00–18:00",
               "first": "Sau khi được tư vấn, bạn có thể nộp đơn khiếu nại trên Cổng thông tin Lao động (노동포털) hoặc đến Sở Việc làm và Lao động khu vực."},
        "zh": {"label": "拖欠工资等职场问题", "agency": "雇佣劳动部客户咨询中心（고용노동부 고객상담센터）",
               "operator": "雇佣劳动部", "hours": "工作日 09:00~18:00",
               "first": "咨询后，可以在劳动门户网站（노동포털）提交陈情书，或前往管辖地区的地方雇佣劳动厅。"},
        "th": {"label": "ค้างค่าจ้างและปัญหาในที่ทำงาน", "agency": "ศูนย์บริการลูกค้ากระทรวงการจ้างงานและแรงงาน (고용노동부 고객상담센터)",
               "operator": "กระทรวงการจ้างงานและแรงงาน", "hours": "วันธรรมดา 09:00–18:00",
               "first": "หลังรับคำปรึกษาแล้ว สามารถยื่นคำร้องทางพอร์ทัลแรงงาน (노동포털) หรือไปที่สำนักงานการจ้างงานและแรงงานในพื้นที่"},
        "id": {"label": "Upah tidak dibayar dan masalah tempat kerja", "agency": "Pusat Layanan Pelanggan Kementerian Ketenagakerjaan Korea (고용노동부 고객상담센터)",
               "operator": "Kementerian Ketenagakerjaan dan Tenaga Kerja Korea", "hours": "Hari kerja 09.00–18.00",
               "first": "Setelah konsultasi, Anda dapat mengajukan petisi di Portal Ketenagakerjaan (노동포털) atau datang ke kantor ketenagakerjaan wilayah setempat."},
        "uz": {"label": "Ish haqi to'lanmasligi va ish joyidagi muammolar", "agency": "Bandlik va mehnat vazirligi mijozlar markazi (고용노동부 고객상담센터)",
               "operator": "Bandlik va mehnat vazirligi", "hours": "Ish kunlari 09:00–18:00",
               "first": "Maslahatdan so'ng Mehnat portalida (노동포털) shikoyat arizasini topshirishingiz yoki hududiy bandlik va mehnat boshqarmasiga borishingiz mumkin."},
        "en": {"label": "Unpaid wages and workplace problems", "agency": "Ministry of Employment and Labor Customer Center (고용노동부 고객상담센터)",
               "operator": "Ministry of Employment and Labor", "hours": "Weekdays 09:00–18:00",
               "first": "After counseling, you can file a petition on the Labor Portal (노동포털) or visit your regional employment and labor office."},
        "ja": {"label": "賃金未払いなど職場の問題", "agency": "雇用労働部 顧客相談センター（고용노동부 고객상담센터）",
               "operator": "雇用労働部", "hours": "平日 09:00〜18:00",
               "first": "相談を受けた後、労働ポータル（노동포털）で陳情書を出すか、管轄の地方雇用労働庁を訪問してください。"},
    },
    "crime": {
        "vi": {"label": "Lừa đảo và các tội phạm khác", "agency": "Cảnh sát (Hệ thống báo cáo tội phạm mạng / đồn cảnh sát gần nhất, 경찰서)",
               "operator": "Cơ quan Cảnh sát Quốc gia Hàn Quốc", "phone": "112 (khi khẩn cấp)", "hours": "Báo cáo trực tuyến 24 giờ",
               "first": "Với lừa đảo qua mạng, hãy báo cáo trước trên Hệ thống báo cáo tội phạm mạng rồi đến đồn cảnh sát để nộp chính thức. Đừng xóa tin nhắn và lịch sử chuyển tiền, hãy chụp màn hình lại."},
        "zh": {"label": "诈骗等犯罪受害", "agency": "警察（网络犯罪举报系统·附近的警察署 경찰서）",
               "operator": "韩国警察厅", "phone": "112（紧急时）", "hours": "网上举报24小时",
               "first": "网络诈骗请先在网络犯罪举报系统举报，再到警察署正式立案。聊天记录和转账记录不要删除，请截图保存。"},
        "th": {"label": "การฉ้อโกงและอาชญากรรมอื่น ๆ", "agency": "ตำรวจ (ระบบแจ้งอาชญากรรมไซเบอร์ / สถานีตำรวจใกล้บ้าน 경찰서)",
               "operator": "สำนักงานตำรวจแห่งชาติเกาหลี", "phone": "112 (กรณีเร่งด่วน)", "hours": "แจ้งออนไลน์ได้ 24 ชั่วโมง",
               "first": "การฉ้อโกงออนไลน์ให้แจ้งในระบบแจ้งอาชญากรรมไซเบอร์ก่อน แล้วไปแจ้งความอย่างเป็นทางการที่สถานีตำรวจ อย่าลบแชตและหลักฐานการโอนเงิน ให้แคปหน้าจอเก็บไว้"},
        "id": {"label": "Penipuan dan kejahatan lainnya", "agency": "Polisi (Sistem Pelaporan Kejahatan Siber / kantor polisi terdekat, 경찰서)",
               "operator": "Kepolisian Nasional Korea", "phone": "112 (saat darurat)", "hours": "Laporan online 24 jam",
               "first": "Untuk penipuan online, laporkan dulu di Sistem Pelaporan Kejahatan Siber, lalu buat laporan resmi di kantor polisi. Jangan hapus percakapan dan bukti transfer—simpan tangkapan layarnya."},
        "uz": {"label": "Firibgarlik va boshqa jinoyatlar", "agency": "Politsiya (Kiberjinoyatlar haqida xabar berish tizimi / eng yaqin politsiya bo'limi, 경찰서)",
               "operator": "Koreya Milliy politsiya agentligi", "phone": "112 (shoshilinch holatda)", "hours": "Onlayn xabar berish 24 soat",
               "first": "Internetdagi firibgarlik haqida avval Kiberjinoyatlar tizimida xabar bering, so'ng politsiya bo'limida rasman ro'yxatdan o'tkazing. Yozishmalar va pul o'tkazmalari tarixini o'chirmang, skrinshot qilib saqlang."},
        "en": {"label": "Fraud and other crimes", "agency": "Police (Cyber Crime Reporting System / nearest police station, 경찰서)",
               "operator": "Korean National Police Agency", "phone": "112 (in an emergency)", "hours": "Online reports 24 hours",
               "first": "For online fraud, report it first on the Cyber Crime Reporting System, then file it officially at a police station. Don't delete chats or payment records—take screenshots."},
        "ja": {"label": "詐欺などの犯罪被害", "agency": "警察（サイバー犯罪申告システム・最寄りの警察署 경찰서）",
               "operator": "韓国警察庁", "phone": "112（緊急時）", "hours": "オンライン申告は24時間",
               "first": "ネット詐欺はまずサイバー犯罪申告システムで申告し、その後警察署で正式に受理してもらいます。チャットや振込の記録は消さずにスクリーンショットを残してください。"},
    },
    "legal": {
        "vi": {"label": "Tranh chấp pháp lý giữa cá nhân", "agency": "Tư vấn pháp lý 132 của Tổng công ty Trợ giúp Pháp lý Hàn Quốc (대한법률구조공단)",
               "operator": "Tổng công ty Trợ giúp Pháp lý Hàn Quốc", "hours": "Ngày thường 09:00–18:00 (trừ giờ nghỉ trưa)",
               "first": "Cơ quan hành chính không thể phân xử tranh chấp giữa các cá nhân, vì vậy tốt nhất là nhận tư vấn pháp lý miễn phí để biết cách giải quyết."},
        "zh": {"label": "个人之间的法律纠纷", "agency": "大韩法律救助公团132法律咨询（대한법률구조공단）",
               "operator": "大韩法律救助公团", "hours": "工作日 09:00~18:00（午休除外）",
               "first": "个人之间的纠纷行政机关无法代为裁决，建议通过免费法律咨询了解解决办法。"},
        "th": {"label": "ข้อพิพาททางกฎหมายระหว่างบุคคล", "agency": "บริการปรึกษากฎหมาย 132 ของบรรษัทช่วยเหลือทางกฎหมายเกาหลี (대한법률구조공단)",
               "operator": "บรรษัทช่วยเหลือทางกฎหมายเกาหลี", "hours": "วันธรรมดา 09:00–18:00 (ยกเว้นพักเที่ยง)",
               "first": "หน่วยงานรัฐไม่สามารถตัดสินข้อพิพาทระหว่างบุคคลแทนได้ จึงควรรับคำปรึกษากฎหมายฟรีเพื่อทราบวิธีแก้ไข"},
        "id": {"label": "Sengketa hukum antarpribadi", "agency": "Konsultasi hukum 132 Korporasi Bantuan Hukum Korea (대한법률구조공단)",
               "operator": "Korporasi Bantuan Hukum Korea", "hours": "Hari kerja 09.00–18.00 (kecuali jam makan siang)",
               "first": "Instansi pemerintah tidak bisa memutuskan sengketa antarpribadi, jadi sebaiknya dapatkan konsultasi hukum gratis untuk mengetahui cara penyelesaiannya."},
        "uz": {"label": "Shaxslar o'rtasidagi huquqiy nizolar", "agency": "Koreya yuridik yordam korporatsiyasi 132 huquqiy maslahat (대한법률구조공단)",
               "operator": "Koreya yuridik yordam korporatsiyasi", "hours": "Ish kunlari 09:00–18:00 (tushlikdan tashqari)",
               "first": "Shaxslar o'rtasidagi nizolarni davlat idoralari hal qilib bera olmaydi, shuning uchun bepul huquqiy maslahat orqali yechim yo'llarini bilib olish ma'qul."},
        "en": {"label": "Legal disputes between individuals", "agency": "Korea Legal Aid Corporation 132 legal counseling (대한법률구조공단)",
               "operator": "Korea Legal Aid Corporation", "hours": "Weekdays 09:00–18:00 (except lunch)",
               "first": "Government offices can't settle disputes between individuals for you, so free legal counseling is the best way to learn your options."},
        "ja": {"label": "個人間の法的トラブル", "agency": "大韓法律救助公団 132法律相談（대한법률구조공단）",
               "operator": "大韓法律救助公団", "hours": "平日 09:00〜18:00（昼休みを除く）",
               "first": "個人間のトラブルは行政機関が代わりに決めることができないため、無料の法律相談で解決方法を教えてもらうのがよいです。"},
    },
}
