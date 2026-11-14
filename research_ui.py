"""Bảng điều khiển minh chứng kỹ thuật. Không suy diễn hiệu quả giáo dục."""
import json
import streamlit as st
from research_suite import run_reference_suite


def research_ui():
    st.markdown('### 📊 Phòng minh chứng khoa học')
    st.caption('Kiểm thử độc lập với Gemini trên các trường hợp SMILES biên soạn sẵn. Không phải dữ liệu học sinh hay kết quả so sánh chatbot.')
    st.info('Nhấn chạy để tạo dữ liệu đo từ phiên hiện tại. Không hiển thị tỷ lệ chính xác nhận dạng ảnh khi chưa có bộ ảnh gán nhãn.')
    if st.button('▶ Chạy bộ kiểm thử tham chiếu',type='primary',key='run_research_suite'):
        with st.spinner('Đang chạy RDKit...'):
            st.session_state['research_run']=run_reference_suite()
    result=st.session_state.get('research_run')
    if result:
        summary=result['summary']
        a,b,c=st.columns(3)
        a.metric('Ca đã chạy',summary['total'])
        b.metric('Ca đạt',summary['passed'])
        c.metric('Ca chưa đạt',summary['failed'])
        st.dataframe(result['records'],hide_index=True,use_container_width=True)
        st.caption(f"RDKit {result['metadata']['rdkit_version']} · {result['metadata']['created_utc']} · Thời gian trung bình {summary['mean_elapsed_ms']} ms/ca")
        st.download_button('📥 Xuất báo cáo thực thi JSON',json.dumps(result,ensure_ascii=False,indent=2),
                           file_name='molsnap_minh_chung_thuc_thi.json',mime='application/json')
    with st.expander('Giới hạn và kế hoạch đánh giá khoa học'):
        st.markdown('''**Đã đo tại đây:** kiểm tra SMILES và đối chiếu cấu tạo trên bộ ca nhỏ có đáp án biên soạn trước.\n\n**Chưa đo:** độ chính xác Gemini đọc ảnh viết tay, tính đầy đủ thuật toán đồng phân, độ đúng của phản ứng, thời gian xử lý API và mức cải thiện học tập.\n\n**Để đánh giá chính thức:** xây bộ ảnh có nhãn, tách tập phát triển/kiểm thử, ghi lỗi nhận dạng và lỗi hóa học riêng, đối chiếu mù với công cụ nền, báo cáo số lượng mẫu và khoảng tin cậy.''')
