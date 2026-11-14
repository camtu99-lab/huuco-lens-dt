"""Phòng thử thách có thể demo trực tiếp, không cần API Gemini."""
import json
import streamlit as st
from challenge_engine import TASKS, evaluate_task, make_event, summarize, staged_hints


def challenge_ui():
    st.markdown('### 🎯 Thử thách nhà hóa học – Học bằng cách tự sửa')
    st.caption('5 bài thực hành có đáp án biên soạn trước. RDKit kiểm tra cấu tạo, không dùng AI để tự chấm.')
    st.session_state.setdefault('challenge_events', [])
    st.session_state.setdefault('challenge_result', None)
    st.session_state.setdefault('challenge_hint_level', 0)
    st.session_state.setdefault('challenge_task', TASKS[0]['id'])
    task_id = st.selectbox('Chọn bài thực hành', [t['id'] for t in TASKS],
                           format_func=lambda v: next(t['title'] for t in TASKS if t['id'] == v),
                           key='challenge_task')
    task = next(t for t in TASKS if t['id'] == task_id)
    st.info(f"**Nhiệm vụ {task['id']} · {task['difficulty']}:** {task['prompt']}")
    st.caption(f"Năng lực luyện tập: {task['skill']}. Bạn có thể nhập một SMILES khác nhưng biểu diễn cùng cấu tạo.")
    with st.form('challenge_answer_form'):
        answer = st.text_input('SMILES của bạn', key=f'challenge_answer_{task_id}', max_chars=2000,
                               placeholder='Nhập cấu trúc rồi nhấn Kiểm tra')
        submitted = st.form_submit_button('🧪 Kiểm chứng bài làm', type='primary')
    if submitted:
        result = evaluate_task(task_id, answer)
        events = st.session_state.challenge_events
        events.append(make_event(task_id, answer, result,
                                 1 + sum(e['task_id'] == task_id for e in events)))
        st.session_state.challenge_result = {'task_id':task_id, 'result':result}
        st.session_state.challenge_hint_level = 0
    current = st.session_state.challenge_result
    if current and current['task_id'] == task_id:
        result = current['result']
        if result['correct']:
            st.success('✅ Đúng cấu tạo! ' + result['message'])
        else:
            st.warning('🔎 Chưa đạt: ' + result['message'])
            hints = staged_hints(task_id, result['category'])
            level = st.session_state.challenge_hint_level
            if level < len(hints) and st.button(f'💡 Mở gợi ý {level+1}/{len(hints)}', key=f'challenge_hint_{task_id}_{level}'):
                st.session_state.challenge_hint_level = level + 1
                st.rerun()
            for i, hint in enumerate(hints[:st.session_state.challenge_hint_level], 1):
                st.info(f'**Gợi ý {i}:** {hint}')
            with st.expander('Xem đáp án tham chiếu sau khi đã thử'):
                st.code(task['target'], language=None)
                st.caption('Đây là một cách viết SMILES đúng; có thể có cách viết tương đương.')
    metrics = summarize(st.session_state.challenge_events)
    st.markdown('#### 📈 Tiến độ thực hành trong phiên')
    a,b,c = st.columns(3)
    a.metric('Bài đã thử', f"{metrics['tasks_attempted']}/{metrics['tasks_total']}")
    b.metric('Bài từng làm đúng', metrics['tasks_mastered'])
    c.metric('Lượt thử cần sửa', metrics['incorrect_attempts'])
    st.progress(metrics['tasks_mastered'] / metrics['tasks_total'])
    st.caption('Các chỉ số trên chỉ mô tả lượt thử của phiên hiện tại, không phải hiệu quả giáo dục đã được nghiên cứu.')
    if st.session_state.challenge_events:
        with st.expander('Nhật ký có thể kiểm tra lại'):
            st.dataframe(st.session_state.challenge_events, use_container_width=True, hide_index=True)
            st.download_button('📥 Xuất minh chứng JSON',
                               json.dumps({'metadata':{'type':'session_practice','note':'Không phải dữ liệu thực nghiệm độc lập'},
                                           'summary':metrics,'events':st.session_state.challenge_events}, ensure_ascii=False, indent=2),
                               file_name='molsnap_thu_thach_nhat_ky.json', mime='application/json')
        if st.button('Xóa tiến độ phiên', key='challenge_clear'):
            st.session_state.challenge_events = []
            st.session_state.challenge_result = None
            st.session_state.challenge_hint_level = 0
            st.rerun()
