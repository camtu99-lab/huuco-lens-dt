"""Giao diện học sinh: nhận diện cấu trúc từ hình và học qua phản hồi."""
import json
import streamlit as st
from visual_learning import QUESTIONS, image_for, grade, event


def visual_ui():
    st.markdown('### 🎯 Thử thách nhìn hình – Hiểu bản chất Hóa học')
    st.write('**Không cần nhập mã hóa học.** Quan sát các hình cấu tạo, chọn đáp án và xem vì sao đúng hoặc sai.')
    st.session_state.setdefault('visual_events', [])
    qid = st.selectbox('Chọn thử thách', [q['id'] for q in QUESTIONS],
                       format_func=lambda x: next(q['title'] for q in QUESTIONS if q['id']==x), key='visual_qid')
    q = next(q for q in QUESTIONS if q['id']==qid)
    st.info(q['question'])
    cols = st.columns(3)
    for col, (letter, smiles) in zip(cols, q['choices']):
        with col:
            st.image(image_for(smiles), use_container_width=True)
            st.caption(f'Phương án {letter}')
    with st.form('visual_form'):
        selected = st.radio('Bạn chọn hình nào?', [x[0] for x in q['choices']], horizontal=True,
                            index=None, key=f'visual_pick_{qid}')
        submitted = st.form_submit_button('Kiểm tra đáp án', type='primary')
    if submitted:
        if selected is None:
            st.warning('Hãy chọn một hình trước khi kiểm tra.')
        else:
            result = grade(qid, selected)
            st.session_state['visual_last'] = {'qid':qid, 'result':result}
            st.session_state.visual_events.append(event(qid, selected, result))
    last = st.session_state.get('visual_last')
    if last and last['qid']==qid:
        r = last['result']
        if not r['verified']:
            st.error(r['message'])
        elif r['correct']:
            st.success('🌟 '+r['message'])
        else:
            st.warning('🔎 '+r['message'])
            st.info('💡 Gợi ý tự sửa: '+q['hint'])
            st.caption('Bạn có thể chọn lại đáp án và nhấn Kiểm tra lần nữa.')
    events = st.session_state.visual_events
    mastered = {e['question_id'] for e in events if e['correct'] and e['verified']}
    st.markdown('#### 🌱 Tiến độ luyện tập của bạn')
    a,b,c=st.columns(3)
    a.metric('Bài đã làm đúng',f'{len(mastered)}/{len(QUESTIONS)}')
    b.metric('Lượt đã thử',len(events))
    c.metric('Lượt cần sửa',sum(not e['correct'] for e in events))
    st.progress(len(mastered)/len(QUESTIONS))
    st.caption('Chỉ là tiến độ của phiên học hiện tại; không phải kết quả nghiên cứu hiệu quả giáo dục.')
    with st.expander('📥 Xuất nhật ký học tập (tùy chọn)'):
        st.download_button('Tải nhật ký JSON',json.dumps(events,ensure_ascii=False,indent=2),
                           file_name='molsnap_luyen_tap_hinh_anh.json',mime='application/json')
    with st.expander('Dành cho giáo viên: kiểm tra cấu trúc nâng cao'):
        st.caption('Chế độ nhập SMILES kỹ thuật vẫn được giữ ở phần Kiểm chứng nâng cao.')
