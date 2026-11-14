"""Giao diện luyện tập kiểm chứng: không gọi API, lưu lịch sử trong phiên."""
import json
import base64
import streamlit as st
from learning_lab import diagnose, record_attempt
from challenge_ui import challenge_ui


def learning_ui():
    st.markdown('### 🧪 Phòng thực hành: Kiểm chứng và tự sửa cấu trúc')
    mode = st.radio('Chọn chế độ học', ['🎯 Thử thách có chấm bài', '🔬 Kiểm chứng SMILES tự do'], horizontal=True, key='learning_mode')
    if mode == '🎯 Thử thách có chấm bài':
        challenge_ui()
        return
    st.caption('AI có thể hỗ trợ nhận dạng ở mục Công thức cấu tạo; tại đây RDKit kiểm tra độc lập. Không cần Gemini API key.')
    a, b, c = st.columns(3)
    a.markdown('**① Nhập cấu trúc**')
    b.markdown('**② Kiểm chứng bằng RDKit**')
    c.markdown('**③ Nhận gợi ý và thử lại**')
    st.info('RDKit kiểm tra tính hợp lệ của biểu diễn phân tử. Không thể tự xác nhận hình vẽ gốc, tính đúng của tên chất hoặc mọi điều kiện hóa học.')
    st.session_state.setdefault('learn_attempts', [])
    st.session_state.setdefault('learn_result', None)
    st.session_state.setdefault('learn_level', 0)
    transfer = st.session_state.pop('learning_transfer', None)
    if transfer:
        st.session_state['learn_student_input'] = transfer['smiles']
        st.session_state['learn_transfer_notice'] = transfer['note']
    if st.session_state.get('learn_transfer_notice'):
        st.warning('📷 Đã nhận kết quả từ mục Công thức cấu tạo. ' + st.session_state['learn_transfer_notice'] + '. Hãy kiểm tra lại cấu trúc trước khi kết luận lỗi do học sinh.')
    with st.form('learning_form'):
        student = st.text_input('SMILES bài làm của học sinh', placeholder='Ví dụ: CC(=O)(O)O', max_chars=2000, key='learn_student_input')
        target = st.text_input('SMILES đáp án tham chiếu (tùy chọn, do giáo viên cung cấp)', placeholder='Ví dụ: CC(=O)O', max_chars=2000)
        st.caption('Để trống đáp án tham chiếu nếu chỉ muốn kiểm tra cú pháp và hóa trị. Cấu trúc hợp lệ chưa chắc đúng đề bài.')
        submitted = st.form_submit_button('🔬 Kiểm chứng / Kiểm tra lại', type='primary')
    if submitted:
        result = diagnose(student, target)
        st.session_state.learn_result = result
        st.session_state.learn_level = 0
        st.session_state.learn_attempts.append(record_attempt(student, target, result, len(st.session_state.learn_attempts) + 1))
    result = st.session_state.learn_result
    if result:
        v = result['verification']
        status = result['verdict']
        if status == 'matches_target':
            st.success('Cấu trúc trùng đáp án tham chiếu theo biểu diễn lập thể của RDKit.')
        elif status in ('invalid', 'constitution_differs', 'formula_differs', 'stereo_differs'):
            st.warning({'invalid': 'Cấu trúc hoặc cách viết SMILES không hợp lệ.',
                        'constitution_differs': 'Cùng công thức phân tử, khác cách nối nguyên tử.',
                        'formula_differs': 'Công thức phân tử khác đáp án tham chiếu.',
                        'stereo_differs': 'Cùng cấu tạo nhưng khác biểu diễn lập thể.'}[status])
        elif status == 'valid_only':
            st.success('Cấu trúc qua kiểm tra RDKit; chưa đối chiếu với đề bài.')
        else:
            st.info('Chưa thể kết luận đầy đủ. Hãy xem chi tiết kiểm chứng.')
        st.write('**Kết quả RDKit:**', v['message'])
        x, y = st.columns(2)
        x.metric('Trạng thái', {'valid': 'Hợp lệ', 'invalid': 'Không hợp lệ', 'unknown': 'Chưa xác minh'}[v['status']])
        y.metric('Công thức phân tử', v['formula'] or '—')
        if v['atom_indices']:
            st.write('**Nguyên tử nghi vấn (thứ tự SMILES bắt đầu từ 1):**', ', '.join(str(i + 1) for i in v['atom_indices']))
        if result['highlight_svg']:
            # st.image/Pillow không đọc trực tiếp dữ liệu SVG. Hiển thị qua data URI trong trình duyệt.
            svg_data = base64.b64encode(result['highlight_svg'].encode('utf-8')).decode('ascii')
            st.markdown(
                f'<img src="data:image/svg+xml;base64,{svg_data}" alt="Minh họa RDKit về nguyên tử nghi vấn" style="width:100%;max-width:640px;height:auto"/>',
                unsafe_allow_html=True,
            )
            st.caption('Hình RDKit dựng từ SMILES; tô sáng vị trí nghi vấn, không phải ảnh gốc')
        st.markdown('#### 💡 Hướng dẫn sửa lỗi theo từng bước')
        hints = result['hints']
        if hints:
            st.info(f'**Gợi ý {min(st.session_state.learn_level + 1, len(hints))}/{len(hints)}:** {hints[min(st.session_state.learn_level, len(hints)-1)]}')
            if st.session_state.learn_level < len(hints) - 1:
                if st.button('Xem gợi ý tiếp theo', key='learn_next'):
                    st.session_state.learn_level += 1
                    st.rerun()
        if v['canonical_smiles']:
            with st.expander('Xem SMILES chuẩn hóa và phạm vi kiểm tra'):
                st.code(v['canonical_smiles'])
                for item in v['checked']:
                    st.write('✓', item)
                for item in v['limitations']:
                    st.caption(item)
        if status == 'target_unverified':
            st.error('Không dùng đáp án tham chiếu chưa kiểm chứng để chấm bài học sinh.')
    st.divider()
    st.markdown('#### 📋 Nhật ký thử lại (chỉ lưu trong phiên)')
    attempts = st.session_state.learn_attempts
    if attempts:
        st.dataframe(attempts, use_container_width=True, hide_index=True)
        st.download_button('Tải nhật ký JSON', json.dumps(attempts, ensure_ascii=False, indent=2),
                           file_name='molsnap_nhat_ky_kiem_chung.json', mime='application/json')
        if st.button('Xóa nhật ký phiên', key='learn_clear'):
            st.session_state.learn_attempts = []
            st.session_state.learn_result = None
            st.rerun()
    else:
        st.caption('Chưa có lượt kiểm tra trong phiên này. Không lưu dữ liệu cá nhân lên máy chủ.')
