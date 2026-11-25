"""Song ngữ Việt – Anh (bilingual Vietnamese – English) cho MolSnap.

Ba chế độ, chọn ở thanh bên (session_state["lang"]):
    "vi"  Tiếng Việt (mặc định, giao diện cũ giữ nguyên)
    "bi"  Việt – Anh: mỗi nhãn hiện "tiếng Việt · English"
    "en"  English

Cách hoạt động:
  * `tx(vi, en=None)` trả về chuỗi theo chế độ hiện tại. Nếu không đưa `en`, tra trong từ điển EN.
  * `install()` bọc các hàm st.button / st.radio / st.caption ... để nhãn tự được dịch
    mà không phải sửa từng chỗ gọi. Giá trị trả về của radio/selectbox vẫn là chuỗi tiếng Việt gốc,
    nên mã so sánh kiểu `mode.startswith("📷")` không bị ảnh hưởng.
  * `ai_note()` là đoạn chỉ thị gắn vào lời nhắc gửi AI để kết quả cũng song ngữ.
Chuỗi chưa có trong từ điển được giữ nguyên tiếng Việt (không bao giờ gây lỗi).
"""
import re

import streamlit as st

LANGS = ["vi", "bi", "en"]
LANG_NAMES = {"vi": "Tiếng Việt", "bi": "Việt – Anh", "en": "English"}

# ---------------------------------------------------------------------------
# Từ điển Việt -> Anh. Khóa là chuỗi gốc, KHÔNG gồm emoji/ký hiệu đứng đầu (xử lý tự động).
# ---------------------------------------------------------------------------
EN = {
    # --- điều hướng, trang ---
    "Trang chủ": "Home",
    "Công thức cấu tạo": "Structure",
    "Phương trình phản ứng": "Reactions",
    "Đồng phân": "Isomers",
    "Dụng cụ hóa học": "Lab equipment",
    "Sơ đồ tư duy": "Mind map",
    "Trợ lý AI": "AI assistant",
    "Lịch sử học sinh": "Student history",
    "Xem lại những gì bạn đã tra cứu ở từng tab; giáo viên xem được cả lớp.": "Review what you looked up in each tab; teachers can see the whole class.",
    "Chế độ gợi ý từng bước (không đưa đáp án ngay)": "Step-by-step hints (don't give the answer at once)",
    "Làm bài, máy chấm ngay và gợi ý từng bước; giáo viên có thể giao bài cho cả lớp.": "Do exercises with instant grading and step-by-step hints; teachers can assign work to the whole class.",
    "Chế độ": "Mode",
    "Đã làm": "Attempted", "Đúng": "Correct", "Tỉ lệ đúng": "Correct rate",
    "Mã lớp": "Class code", "Tên của em": "Your name", "Học sinh": "Student", "Lớp": "Class",
    "Của tôi": "Mine", "Giáo viên": "Teacher", "Tổng": "Total",
    "Xem ai đã truy cập và tra cứu gì ở từng tab (dành cho giáo viên).": "See who visited and what they looked up in each tab (for teachers).",
    "Công thức cấu tạo viết tay": "Handwritten structural formula",
    "Chụp ảnh công thức vẽ tay kiểu SGK → mã SMILES, tên gọi, khối lượng mol, tính chất.":
        "Photograph a hand-drawn textbook formula → SMILES, name, molar mass, properties.",
    "Đọc phương trình, cho biết loại phản ứng và kiểm tra đã cân bằng chưa.":
        "Read an equation, name the reaction type and check whether it is balanced.",
    "Hỏi bằng tiếng Việt hoặc gõ công thức, máy sinh và đếm đồng phân chính xác.":
        "Ask in plain words or type a formula; the engine generates and counts isomers exactly.",
    "Chụp ảnh dụng cụ để biết tên, công dụng, cách dùng, hoặc gõ tên thí nghiệm để xem phim mô phỏng.":
        "Photograph equipment to learn its name and use, or type an experiment to watch a simulation.",
    "Nhập chủ đề hoặc tên chất, máy vẽ sơ đồ để ôn tập, sửa được và tải về PowerPoint, draw.io.":
        "Enter a topic or compound; get an editable review mind map you can export to PowerPoint or draw.io.",
    "Hỏi bất cứ điều gì về hóa học, mình luôn ở đây!": "Ask anything about chemistry, I'm always here!",
    # --- trang chủ ---
    "Khám phá nhanh": "Quick start",
    "Nhập nhanh": "Quick entry",
    "Nhập công thức để tra cứu ngay": "Type a formula to look it up now",
    "Tài liệu học tập": "Study resources",
    "Kho tài liệu & công thức quan trọng": "Key reference tables & formulas",
    "Lịch sử tra cứu": "Lookup history",
    "Chào bạn !": "Hello!",
    "Khám phá thế giới Hóa học": "Explore the world of Chemistry",
    "cùng": "with",
    "Nhanh chóng": "Fast",
    "Chính xác": "Accurate",
    "Thông minh": "Smart",
    "Tiện lợi": "Handy",
    "Học mọi lúc": "Learn anytime",
    "Mỗi phản ứng": "Every reaction",
    "là một khám phá!": "is a discovery!",
    "Chụp nhanh": "Snap it",
    "Nhận kết quả ngay!": "Get results at once!",
    "Học hóa": "Chemistry",
    "thật dễ!": "made easy!",
    "AI trong tay – Hóa học dễ dàng": "AI in hand – Chemistry made easy",
    "Hỏi bất cứ điều gì về": "Ask anything about",
    "hóa học, mình luôn ở đây!": "chemistry, I'm always here!",
    "Chưa có lượt tra cứu nào. Hãy thử Nhập nhanh hoặc dùng một công cụ bên trái.":
        "No lookups yet. Try Quick entry or one of the tools on the left.",
    "Hóa học không khó, chỉ cần bạn có công cụ đúng!": "Chemistry isn't hard, you just need the right tools!",
    "Tìm kiếm": "Search",
    "Tìm công cụ, công thức, tên chất…": "Search tools, formulas, compounds…",
    "Mở": "Open",
    "Mở trợ lý AI": "Open the AI assistant",
    "Công thức": "Formula",
    "VD: C4H10O, CCO, axit axetic…": "e.g. C4H10O, CCO, acetic acid…",
    "Bảng tuần hoàn": "Periodic table",
    "Bảng tính tan": "Solubility table",
    "Công thức hữu cơ": "Organic formulas",
    "Mẹo & lưu ý": "Tips & notes",
    "Xóa lịch sử": "Clear history",
    "Tải ảnh công thức": "Upload formula image",
    "Điều hướng": "Navigation",
    # --- loại lượt tra cứu (lịch sử) ---
    "Phản ứng": "Reaction",
    "Dụng cụ": "Equipment",
    "Sơ đồ": "Mind map",
    "Mô phỏng": "Simulation",
    "Luyện tập": "Practice",
    "Kiểm tra": "Tests",
    "Xem điểm và bài làm kiểm tra của học sinh.": "See students' test scores and work.",
    "Làm bài kiểm tra giáo viên giao và xem điểm.": "Take the tests your teacher assigned and see your scores.",
    "Hỏi đáp": "Q&A",
    # --- công cụ chung ---
    "Nguồn phương trình": "Equation source",
    "Tải ảnh": "Upload image",
    "Chụp ảnh": "Take photo",
    "Gõ phương trình": "Type equation",
    "Nhận dạng và phân loại phản ứng": "Identify and classify the reaction",
    "Lọc theo nhóm": "Filter by group",
    "Liệt kê đồng phân": "List isomers",
    "So sánh hai chất": "Compare two compounds",
    "Chức năng": "Function",
    "Nhận biết dụng cụ": "Identify equipment",
    "Mô phỏng thí nghiệm": "Experiment simulation",
    "Nguồn": "Source",
    "Gõ tên dụng cụ": "Type equipment name",
    "Chọn đề cụ thể (hoặc để ngẫu nhiên)": "Pick a question (or leave random)",
    "Phương pháp đọc ảnh": "Image reading method",
    "Nguồn ảnh": "Image source",
    "Tải ảnh lên": "Upload image",
    "Mức chi tiết": "Level of detail",
    "Gọn (4 nhánh, mỗi nhánh 2-3 ý)": "Compact (4 branches, 2-3 points each)",
    "Đầy đủ (6 nhánh, mỗi nhánh 3-4 ý)": "Full (6 branches, 3-4 points each)",
    "Cách tạo sơ đồ": "How to build the map",
    "Từ chủ đề": "From a topic",
    "Từ ảnh sơ đồ tôi vẽ tay": "From my hand-drawn map",
    "Cách nhập": "Input method",
    "Nhập SMILES": "Enter SMILES",
    "Phân tích": "Analyze",
    "Tạo mô phỏng": "Create simulation",
    "Tạo sơ đồ tư duy": "Create mind map",
    "Số hóa sơ đồ này": "Digitize this map",
    "Đếm đồng phân": "Count isomers",
    "So sánh": "Compare",
    "Hóa hữu cơ": "Organic",
    "Hóa vô cơ": "Inorganic",
    "Oxi hóa – khử": "Redox",
    "Mở công cụ Công thức cấu tạo": "Open the Structure tool",
    "Mở công cụ Phương trình phản ứng": "Open the Reactions tool",
    "Tra cứu một nguyên tố": "Look up an element",
    "Thống kê theo nhóm": "Statistics by group",
    "Tùy chọn": "Options",
    "Phạm vi khi chỉ nhập công thức": "Scope when only a formula is given",
    "Đơn chức, mạch hở (đề SGK)": "Monofunctional, open-chain (textbook)",
    "Phổ thông (cả đa chức và 1 vòng)": "General (incl. polyfunctional and one ring)",
    "Toán học (mọi cấu trúc)": "Mathematical (all structures)",
    "Gọi tên bằng AI (có thể sai)": "Name with AI (may be wrong)",
    "Hoặc dùng ảnh công thức": "Or use a formula image",
    "Ảnh dụng cụ hoặc bộ thí nghiệm": "Photo of equipment or a setup",
    "Chụp dụng cụ hoặc bộ thí nghiệm": "Photograph equipment or a setup",
    "Tên dụng cụ": "Equipment name",
    "Ví dụ: ống sinh hàn": "e.g. Liebig condenser",
    "Chọn ảnh phương trình": "Choose an equation image",
    "Chụp phương trình": "Photograph the equation",
    "Mã SMILES": "SMILES code",
    "Ví dụ: CC(=O)O": "e.g. CC(=O)O",
    "Chọn ảnh công thức (viết rõ nét, nền sáng, mỗi ảnh một chất)":
        "Choose a formula image (clear writing, light background, one compound per image)",
    "Chụp công thức (viết rõ nét, nền sáng, mỗi ảnh một chất)":
        "Photograph the formula (clear writing, light background, one compound per image)",
    "Chọn ảnh sơ đồ tư duy vẽ tay (đủ sáng, chụp thẳng góc, chữ rõ nét)":
        "Choose a hand-drawn mind-map image (good light, straight-on, clear text)",
    "Chụp sơ đồ vẽ tay (đủ sáng, chụp thẳng góc, chữ rõ nét)":
        "Photograph the hand-drawn map (good light, straight-on, clear text)",
    "Nhận dạng sai? Sửa SMILES rồi phân tích lại": "Misread? Fix the SMILES and analyze again",
    "Phân tích lại từ SMILES đã sửa": "Re-analyze from the corrected SMILES",
    "Xóa cuộc trò chuyện": "Clear the conversation",
    "Hỏi bất cứ điều gì về hóa học…": "Ask anything about chemistry…",
    "Chủ đề ở giữa sơ đồ": "Topic at the centre of the map",
    "Ảnh gốc để đối chiếu": "Original image for comparison",
    "Cấu trúc chất (kiểm tra xem đúng chất bạn muốn chưa)": "Compound structure (check it is the one you meant)",
    "Chỉnh sửa nội dung (sửa chữ, thêm hoặc xóa dòng, sơ đồ cập nhật ngay)":
        "Edit content (edit text, add or delete rows; the map updates at once)",
    "Chỉnh thời gian từng bước tùy ý": "Adjust the time of each step",
    "Tự động theo lời đọc (khuyên dùng)": "Automatic, follow the narration (recommended)",
    "Màn kết luận (giây)": "Conclusion screen (seconds)",
    "Áp dụng thời gian": "Apply timing",
    "Tải ảnh PNG": "Download PNG",
    "Tải CSV": "Download CSV",
    # --- luyện tập / giáo viên ---
    "Dạng bài": "Exercise type",
    "Vẽ công thức cấu tạo": "Draw the structural formula",
    "Gọi tên chất": "Name the compound",
    "Tên học sinh (không bắt buộc)": "Student name (optional)",
    "Gợi ý: hiện công thức phân tử": "Hint: show the molecular formula",
    "Nộp bài bằng": "Submit by",
    "Ảnh bài làm": "Photo of my work",
    "Chụp bài làm": "Photograph my work",
    "SMILES bài làm": "SMILES of my answer",
    "Tên chất (theo SGK)": "Compound name (textbook style)",
    "Nộp bài": "Submit",
    "Câu tiếp theo": "Next question",
    "Xem đáp án": "Show the answer",
    "Mã giáo viên": "Teacher code",
    "Mật khẩu lớp học": "Class password",
    # --- thông báo ---
    "Đang phân tích…": "Analyzing…",
    "Đang tính…": "Calculating…",
    "Đang suy nghĩ…": "Thinking…",
    "Đang vẽ sơ đồ…": "Drawing the map…",
    "Đang đọc sơ đồ vẽ tay…": "Reading the hand-drawn map…",
    "Đang đọc bài làm…": "Reading your work…",
    "Đang lập kịch bản và dựng phim…": "Writing the script and building the animation…",
    "Đang thu giọng đọc tự nhiên…": "Recording the natural narration…",
    "Đang chuyển giọng nói thành chữ…": "Converting speech to text…",
    "Nhập bằng giọng nói": "Voice input",
    "Bấm micro để nói, nói xong bấm dừng": "Click the mic to speak, click again to stop",
    "Chưa nhận dạng được công thức trong ảnh.": "Could not recognise a formula in the image.",
    "Mã SMILES không hợp lệ. Hãy sửa ở ô bên dưới rồi bấm Phân tích lại.":
        "Invalid SMILES. Fix it in the box below and press Analyze again.",
    "**Không phải** phản ứng oxi hóa khử.": "This is **not** a redox reaction.",
    "Không tìm thấy phương trình phản ứng nào trong dữ liệu đầu vào.": "No reaction equation found in the input.",
    "Không đọc được một trong hai chất. Hãy kiểm tra lại ảnh hoặc nhập SMILES.":
        "Could not read one of the two compounds. Check the image or enter a SMILES.",
    "Chưa nhận ra dụng cụ thí nghiệm nào trong ảnh.": "No lab equipment recognised in the image.",
    "Độ tin cậy thấp, hãy hỏi giáo viên hoặc chụp lại rõ hơn.": "Low confidence: ask your teacher or retake a clearer photo.",
    "Phương trình trong ảnh **chưa cân bằng** (hệ số chưa đúng).": "The equation in the image is **not balanced** (wrong coefficients).",
    "Phương trình **chưa cân bằng**.": "The equation is **not balanced**.",
    "Sơ đồ đang trống, hãy nhập ít nhất một nhánh.": "The map is empty; enter at least one branch.",
    "Mỗi chất nhập bằng ảnh, SMILES hoặc tên.": "Enter each compound as an image, a SMILES or a name.",
    "Không mở được micro. Hãy cho phép trình duyệt dùng micro cho trang này.":
        "Cannot open the microphone. Allow the browser to use it on this page.",
    "Đoạn ghi âm quá dài, hãy nói ngắn hơn (dưới khoảng 1 phút).": "Recording too long; keep it under about 1 minute.",
    "Không nghe rõ, hãy nói lại gần micro hơn.": "Could not hear you clearly; speak closer to the mic.",
    "Bạn đã dùng hết số lượt của phiên này. Hãy tải lại trang để tiếp tục.":
        "You have used all lookups for this session. Reload the page to continue.",
    "Đã hết số lượt của phiên này.": "No lookups left in this session.",
    "Có lỗi khi phân tích, hãy thử lại hoặc chụp rõ hơn.": "Analysis failed; try again or take a clearer photo.",
    "Có lỗi khi phân tích lại.": "Re-analysis failed.",
    "Có lỗi khi hỏi trợ lý, bạn thử lại sau nhé.": "The assistant ran into a problem; please try again later.",
    "Vì công thức sai hóa trị nên chưa thể gọi tên hay tính khối lượng mol. Hãy sửa lại hình vẽ hoặc sửa SMILES ở ô bên dưới.":
        "Because the formula breaks valence rules, it cannot be named or its molar mass computed yet. Fix the drawing or the SMILES below.",
    "Tab này dành cho giáo viên hoặc nhóm nghiên cứu. Nhập mã giáo viên để dùng.":
        "This tab is for teachers or researchers. Enter the teacher code to use it.",
    "Kết quả này được tạo bởi bản cũ (không có phần Lời giải). Hãy bấm lại nút **Nhận dạng và phân loại phản ứng**.":
        "This result came from an older version (no worked solution). Press **Identify and classify the reaction** again.",
    "Chưa chuyển được giọng nói thành chữ (có thể Gemini đang quá tải hoặc hết hạn mức). Hãy thử lại sau.":
        "Could not convert speech to text (Gemini may be overloaded or out of quota). Try again later.",
    "Phương trình trong kịch bản **chưa cân bằng** theo hệ số đã nêu, hãy kiểm tra lại.":
        "The equation in the script is **not balanced** with the stated coefficients; please check.",
    "AI không nhận ra đề bài/câu hỏi trong ảnh nên chỉ phân tích từng phương trình (không có phần Lời giải).":
        "The AI could not find a question in the image, so it only analysed each equation (no worked solution).",
    # --- chú thích dài ---
    "Kết quả do AI nhận biết qua ảnh nên có thể nhầm, nhất là khi ảnh mờ hoặc dụng cụ bị che. Khi làm thí nghiệm thật, hãy làm theo hướng dẫn của giáo viên và quy định an toàn của phòng thực hành.":
        "Results come from AI image recognition and can be wrong, especially for blurry photos or hidden equipment. For real experiments, follow your teacher's instructions and the lab safety rules.",
    "Phần chấm công thức do RDKit so sánh cấu tạo nên chính xác. Phần đọc ảnh bài làm do AI thực hiện nên có thể đọc sai nét viết khó.":
        "Formula grading is done by RDKit comparing structures, so it is exact. Reading a photo of your work is done by AI and may misread hard handwriting.",
    "Khối lượng nguyên tử tính theo RDKit (đơn vị amu). Số trong ngoặc vuông [ ] là số khối của đồng vị bền nhất, dùng cho nguyên tố không có đồng vị bền.":
        "Atomic masses are from RDKit (amu). A number in square brackets [ ] is the mass number of the most stable isotope, used for elements with no stable isotope.",
    "Các phương trình đã được máy kiểm tra cân bằng nguyên tử. ↑ là chất khí, ↓ là chất kết tủa. Điều kiện ghi trên mũi tên.":
        "Equations have been checked for atom balance. ↑ is a gas, ↓ is a precipitate. Conditions are written above the arrow.",
    "Bỏ chọn “Tự động” rồi nhập số giây cho từng bước. Giọng đọc sẽ tự nhanh hoặc chậm lại cho vừa thời lượng. Muốn nhanh chậm cả phim, kéo thanh tốc độ ⏱ bên dưới phim.":
        "Untick “Automatic” and enter seconds for each step. The voice speeds up or slows down to fit. To change the speed of the whole film, drag the ⏱ slider below it.",
    "PowerPoint: mỗi khung là hình có chữ sửa được và đường nối dính vào khung, kéo khung thì đường nối đi theo. draw.io mở bằng app.diagrams.net. File .mm mở bằng XMind, Freeplane, MindManager.":
        "PowerPoint: each box is a shape with editable text and connectors attached, so connectors follow when you drag a box. Open draw.io files at app.diagrams.net. Open .mm files with XMind, Freeplane or MindManager.",
    "Muốn thêm nhánh mới: thêm dòng mới và gõ tên nhánh mới. Dòng để trống cột Nhánh sẽ thuộc nhánh ngay phía trên.":
        "To add a new branch, add a row and type the new branch name. A row with an empty Branch cell belongs to the branch above it.",
    "Trùng hợp: nCH₂=CH₂ → (–CH₂–CH₂–)ₙ (điều kiện: t°, p, xúc tác).":
        "Polymerisation: nCH₂=CH₂ → (–CH₂–CH₂–)ₙ (conditions: t°, p, catalyst).",
    "Các chất đồng đẳng hơn kém nhau một hoặc nhiều nhóm CH2.": "Homologues differ by one or more CH2 groups.",
    "Chất khử (tính khử) = chất bị oxi hóa. Chất oxi hóa (tính oxi hóa) = chất bị khử.":
        "Reducing agent = the substance that is oxidised. Oxidising agent = the substance that is reduced.",
    # --- bảng tuần hoàn ---
    "Số hiệu (Z)": "Atomic number (Z)",
    "Ký hiệu": "Symbol",
    "Khối lượng": "Mass",
    "Nhóm": "Group",
    # --- Lịch sử (mới) ---
    "Cation (kim loại, H, NH₄)": "Cation (metal, H, NH₄)",
    "Anion (gốc axit, OH)": "Anion (acid radical, OH)",
}

# Tên tiếng Anh các nguyên tố (theo số hiệu 1..118) cho bảng tuần hoàn
ELEMENTS_EN = ("Hydrogen,Helium,Lithium,Beryllium,Boron,Carbon,Nitrogen,Oxygen,Fluorine,Neon,Sodium,Magnesium,Aluminium,Silicon,"
               "Phosphorus,Sulfur,Chlorine,Argon,Potassium,Calcium,Scandium,Titanium,Vanadium,Chromium,Manganese,Iron,Cobalt,"
               "Nickel,Copper,Zinc,Gallium,Germanium,Arsenic,Selenium,Bromine,Krypton,Rubidium,Strontium,Yttrium,Zirconium,"
               "Niobium,Molybdenum,Technetium,Ruthenium,Rhodium,Palladium,Silver,Cadmium,Indium,Tin,Antimony,Tellurium,Iodine,"
               "Xenon,Caesium,Barium,Lanthanum,Cerium,Praseodymium,Neodymium,Promethium,Samarium,Europium,Gadolinium,Terbium,"
               "Dysprosium,Holmium,Erbium,Thulium,Ytterbium,Lutetium,Hafnium,Tantalum,Tungsten,Rhenium,Osmium,Iridium,Platinum,"
               "Gold,Mercury,Thallium,Lead,Bismuth,Polonium,Astatine,Radon,Francium,Radium,Actinium,Thorium,Protactinium,Uranium,"
               "Neptunium,Plutonium,Americium,Curium,Berkelium,Californium,Einsteinium,Fermium,Mendelevium,Nobelium,Lawrencium,"
               "Rutherfordium,Dubnium,Seaborgium,Bohrium,Hassium,Meitnerium,Darmstadtium,Roentgenium,Copernicium,Nihonium,"
               "Flerovium,Moscovium,Livermorium,Tennessine,Oganesson").split(",")
assert len(ELEMENTS_EN) == 118

_LEAD = re.compile(r"^([^\w*]+)(.*)$", re.S)


def lang():
    return st.session_state.get("lang", "vi")


def _lookup(s):
    """Trả về (tiền tố emoji, bản tiếng Anh) hoặc (None, None) nếu chưa có bản dịch."""
    s0 = s.strip()
    if s0 in EN:
        return "", EN[s0]
    m = _LEAD.match(s0)
    if m and m.group(2).strip() in EN:
        return m.group(1), EN[m.group(2).strip()]
    return None, None


def tx(vi, en=None, sep=" · "):
    """Chuỗi theo chế độ ngôn ngữ. `en` bỏ trống thì tra từ điển; không có bản dịch thì giữ tiếng Việt."""
    L = lang()
    if L == "vi" or not isinstance(vi, str) or not vi.strip():
        return vi
    if en is not None:
        pre, e = "", en
    else:
        pre, e = _lookup(vi)
        if e is None:
            return vi
    if L == "en":
        return pre + e
    return f"{vi}{sep}{e}"


def tx_block(vi, en=None, sep="  \n"):
    """Như tx nhưng cho đoạn văn dài: bản Anh xuống dòng bên dưới bản Việt."""
    return tx(vi, en, sep=sep)


def element_name(z, vi_name):
    return tx(vi_name, ELEMENTS_EN[z - 1], sep=" / ")


# ---------------------------------------------------------------------------
# Chỉ thị ngôn ngữ gửi kèm lời nhắc AI
# ---------------------------------------------------------------------------
_KEEP = ("Giữ nguyên mọi khóa JSON, SMILES, công thức hóa học, con số, mã/nhãn cố định và các giá trị chỉ được chọn trong một danh sách "
         "đã nêu ở trên (KHÔNG dịch chúng). Vẫn chỉ trả về đúng định dạng đã yêu cầu, không thêm lời dẫn.")


def ai_note():
    L = lang()
    if L == "en":
        return ("LANGUAGE OVERRIDE: write every free-text value (names, descriptions, explanations, notes, steps, hints) in clear English "
                "for a high-school student; for a compound name give the English name first and the Vietnamese textbook name in "
                "parentheses, e.g. 'ethanol (etanol)'. " + _KEEP)
    if L == "bi":
        return ("LANGUAGE OVERRIDE (BILINGUAL): every free-text value (names, descriptions, explanations, notes, steps, hints) must be "
                "bilingual, Vietnamese first. For a short name/label write 'tên tiếng Việt (English name)', e.g. 'etanol (ethanol)'. "
                "For a sentence write the Vietnamese sentence, then ' | ' and the English sentence. Keep each text short. " + _KEEP)
    return ""


def chat_note():
    L = lang()
    if L == "en":
        return (" LANGUAGE OVERRIDE: ignore the instruction above to answer in Vietnamese; reply in clear, simple English "
                "and add the Vietnamese textbook term in parentheses for key terms.")
    if L == "bi":
        return (" Trả lời SONG NGỮ: trước hết viết phần tiếng Việt, sau đó xuống dòng và viết bản tiếng Anh tương ứng bắt đầu bằng '🇬🇧 '. "
                "Giữ cả hai phần ngắn gọn, cùng nội dung.")
    return ""


def voice_note():
    return "" if lang() == "vi" else " Người nói có thể dùng tiếng Việt hoặc tiếng Anh: chép đúng ngôn ngữ họ nói, không dịch."


# ---------------------------------------------------------------------------
# Bọc các hàm st.* để nhãn tự dịch
# ---------------------------------------------------------------------------
_LABEL_FUNCS = ("button", "text_input", "text_area", "number_input", "file_uploader", "camera_input", "checkbox",
                "selectbox", "multiselect", "radio", "download_button", "form_submit_button", "expander", "chat_input",
                "audio_input", "toggle")
_TEXT_FUNCS = ("caption", "info", "warning", "error", "success")


def _fmt(o):
    return tx(o) if isinstance(o, str) else str(o)


def _make_label(name):
    def w(*args, **kw):
        orig = st.__dict__["_bi_orig"][name]
        if lang() != "vi":
            args = list(args)
            if args and isinstance(args[0], str):
                args[0] = tx(args[0])
            elif isinstance(kw.get("label"), str):
                kw["label"] = tx(kw["label"])
            for k in ("placeholder", "help"):
                if isinstance(kw.get(k), str):
                    kw[k] = tx(kw[k])
            if name in ("radio", "selectbox", "multiselect") and "format_func" not in kw:
                kw["format_func"] = _fmt
        return orig(*args, **kw)
    return w


def _make_text(name):
    def w(*args, **kw):
        orig = st.__dict__["_bi_orig"][name]
        if lang() != "vi" and args and isinstance(args[0], str):
            args = (tx_block(args[0]),) + tuple(args[1:])
        return orig(*args, **kw)
    return w


def _make_spinner():
    def w(*args, **kw):
        orig = st.__dict__["_bi_orig"]["spinner"]
        if lang() != "vi" and args and isinstance(args[0], str):
            args = (tx(args[0]),) + tuple(args[1:])
        return orig(*args, **kw)
    return w


def _make_tabs():
    def w(*args, **kw):
        orig = st.__dict__["_bi_orig"]["tabs"]
        if lang() != "vi" and args and isinstance(args[0], (list, tuple)):
            args = ([tx(x) if isinstance(x, str) else x for x in args[0]],) + tuple(args[1:])
        return orig(*args, **kw)
    return w


def install():
    """Gọi một lần ở đầu mỗi lần chạy. Lặp lại không bao giờ bọc chồng vì luôn gọi hàm gốc đã lưu."""
    orig = st.__dict__.setdefault("_bi_orig", {})
    names = list(_LABEL_FUNCS) + list(_TEXT_FUNCS) + ["spinner", "tabs"]
    for n in names:
        if n not in orig and hasattr(st, n):
            orig[n] = getattr(st, n)
    for n in _LABEL_FUNCS:
        if n in orig:
            setattr(st, n, _make_label(n))
    for n in _TEXT_FUNCS:
        if n in orig:
            setattr(st, n, _make_text(n))
    if "spinner" in orig:
        st.spinner = _make_spinner()
    if "tabs" in orig:
        st.tabs = _make_tabs()
