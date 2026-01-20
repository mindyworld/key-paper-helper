"""
🔑 Key-Paper Helper (필독논문 찾기)
키워드 입력 → 필독 논문 Top 10 추천
"""

import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime
from collections import Counter
from itertools import combinations
import networkx as nx

# 페이지 설정
st.set_page_config(
    page_title="Key-Paper Helper",
    page_icon="🔑",
    layout="wide"
)

# OpenAlex 검색 함수
@st.cache_data(ttl=3600)
def search_openalex(query, year_from, year_to, search_title=True, search_abstract=True, search_keyword=False, max_results=500):
    """OpenAlex API 검색"""
    BASE_URL = "https://api.openalex.org/works"
    all_results = []
    cursor = "*"
    total_count = 0
    
    # 기본 필터
    base_filter = f"publication_year:{year_from}-{year_to}"
    
    while len(all_results) < max_results:
        params = {
            "search": query,  # 기본 검색 (제목+초록+전문)
            "filter": base_filter,
            "per_page": 200,
            "cursor": cursor,
            "select": "id,doi,title,publication_year,cited_by_count,type,authorships,primary_location,abstract_inverted_index"
        }
        
        # 제목만 검색하는 경우
        if search_title and not search_abstract and not search_keyword:
            params.pop("search", None)
            params["filter"] = f"{base_filter},title.search:{query}"
        # 초록만 검색하는 경우
        elif search_abstract and not search_title and not search_keyword:
            params.pop("search", None)
            params["filter"] = f"{base_filter},abstract.search:{query}"
        # 그 외는 기본 search 사용 (제목+초록 모두 검색)
        
        try:
            response = requests.get(BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            total_count = data.get("meta", {}).get("count", 0)
        except Exception as e:
            st.error(f"API 오류: {e}")
            return [], 0
        
        results = data.get("results", [])
        if not results:
            break
            
        all_results.extend(results)
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        
        time.sleep(0.1)
    
    return all_results[:max_results], total_count

def reconstruct_abstract(inverted_index):
    """초록 복원"""
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join([word for _, word in word_positions])

def process_results(results):
    """결과 처리"""
    processed = []
    for work in results:
        authors = []
        author_names = []
        for authorship in work.get("authorships", [])[:10]:
            author = authorship.get("author", {})
            if author.get("display_name"):
                authors.append(author["display_name"])
                author_names.append(author["display_name"])
        
        location = work.get("primary_location", {}) or {}
        source = location.get("source", {}) or {}
        
        # 논문 유형 분류
        title_lower = (work.get("title", "") or "").lower()
        work_type = work.get("type", "")
        
        if "review" in title_lower or "overview" in title_lower or "state-of-the-art" in title_lower:
            paper_type = "Review"
        elif "framework" in title_lower or "model" in title_lower or "theory" in title_lower:
            paper_type = "Framework"
        elif "assess" in title_lower or "evaluat" in title_lower or "measur" in title_lower or "effectiveness" in title_lower:
            paper_type = "Eval"
        else:
            paper_type = "Research"
        
        processed.append({
            "id": work.get("id", ""),
            "title": work.get("title", ""),
            "year": work.get("publication_year"),
            "cited_by_count": work.get("cited_by_count", 0),
            "type": paper_type,
            "authors": "; ".join(authors[:5]),
            "author_list": author_names,
            "journal": source.get("display_name", ""),
            "doi": work.get("doi", ""),
            "abstract": reconstruct_abstract(work.get("abstract_inverted_index"))
        })
    
    return pd.DataFrame(processed)

def calculate_author_centrality(df):
    """저자 중심성 계산"""
    G = nx.Graph()
    
    # 공저 관계로 네트워크 구축
    for _, row in df.iterrows():
        authors = row['author_list'][:5]
        for author in authors:
            if not G.has_node(author):
                G.add_node(author)
        if len(authors) >= 2:
            for pair in combinations(authors, 2):
                if G.has_edge(pair[0], pair[1]):
                    G[pair[0]][pair[1]]['weight'] += 1
                else:
                    G.add_edge(pair[0], pair[1], weight=1)
    
    # 고립 노드 제거
    G.remove_nodes_from(list(nx.isolates(G)))
    
    if len(G.nodes()) < 2:
        return [], []
    
    # 연결 중심성 (Degree Centrality)
    degree_cent = nx.degree_centrality(G)
    top_degree = sorted(degree_cent.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # 매개 중심성 (Betweenness Centrality)
    betweenness_cent = nx.betweenness_centrality(G)
    top_betweenness = sorted(betweenness_cent.items(), key=lambda x: x[1], reverse=True)[:5]
    
    return top_degree, top_betweenness

# 현재 연도
current_year = datetime.now().year

# ==================== 사이드바 ====================
with st.sidebar:
    st.markdown("### 🔑 Key-Paper Helper")
    
    # 🔍 검색어
    st.markdown("**🔍 검색어**")
    search_query = st.text_input(
        "검색어 입력",
        value="",
        placeholder="키워드 입력",
        label_visibility="collapsed",
        help='정확한 구문은 따옴표로 감싸세요'
    )
    
    # 검색 범위
    st.caption("검색 범위:")
    search_title = st.checkbox("제목", value=True, help="논문 제목에서 검색어를 찾습니다. 가장 정확한 결과를 얻을 수 있어요.")
    search_abstract = st.checkbox("초록", value=True, help="논문 초록(Abstract)에서 검색어를 찾습니다. 더 넓은 범위의 관련 논문을 찾을 수 있어요.")
    search_keyword = st.checkbox("주제 태그", value=False, help="OpenAlex가 자동으로 분류한 주제 태그(Concepts)에서 검색합니다. 저자 키워드가 아닌, AI가 부여한 학문 분야 태그입니다.")
    
    st.markdown("")
    
    # 📅 출판 기간
    st.markdown("**📅 출판 기간**")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        year_from = st.selectbox(
            "시작",
            options=list(range(current_year, 1999, -1)),
            index=10,
            label_visibility="collapsed"
        )
    with col2:
        year_to = st.selectbox(
            "종료", 
            options=list(range(current_year, 1999, -1)),
            index=0,
            label_visibility="collapsed"
        )
    
    # 빠른 선택
    st.caption("빠른 선택:")
    last_5y = st.checkbox("최근 5년", value=False)
    last_10y = st.checkbox("최근 10년", value=False)
    last_15y = st.checkbox("최근 15년", value=False)
    
    if last_5y:
        year_from, year_to = current_year - 5, current_year
    elif last_10y:
        year_from, year_to = current_year - 10, current_year
    elif last_15y:
        year_from, year_to = current_year - 15, current_year
    
    st.markdown("---")
    
    search_button = st.button("🔍 검색하기", type="primary", use_container_width=True)
    
    st.markdown("")
    
    if st.button("🏠 처음으로", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    
    st.markdown("")
    st.info("💡 검색어를 입력하고 버튼을 누르면\n**인용 수가 높은 순**으로\n필독 논문을 보여드려요!")

# ==================== 메인 영역 ====================

if search_button and search_query.strip():
    with st.spinner(f"📚 '{search_query}' 관련 논문을 찾는 중..."):
        results, total_count = search_openalex(
            search_query, year_from, year_to,
            search_title=search_title,
            search_abstract=search_abstract,
            search_keyword=search_keyword,
            max_results=500
        )
    
    if results:
        df = process_results(results)
        df_sorted = df.sort_values('cited_by_count', ascending=False)
        
        # 헤더
        st.markdown(f"""
        <h1 style="font-size: 3.5rem; font-weight: bold; color: #1e3a5f; text-align: center; margin-bottom: 0;">
            🔑 Key-Paper Helper
        </h1>
        <h2 style="font-size: 1.8rem; color: #555; text-align: center; margin-top: 0.5rem; margin-bottom: 1.5rem; font-weight: normal;">
            '{search_query}' 검색 결과 ({year_from}-{year_to}) | 총 {total_count:,}건
        </h2>
        """, unsafe_allow_html=True)
        
        # 3개 탭
        tab1, tab2, tab3 = st.tabs(["⭐ 필독 논문 Top 10", "👥 핵심 연구자", "📚 주요 저널"])
        
        # ========== 탭 1: 필독 논문 Top 10 ==========
        with tab1:
            # 헤더 + 다운로드 버튼 (오른쪽 상단)
            col_title, col_download = st.columns([3, 1])
            with col_title:
                st.markdown("### ⭐ 필독 논문 Top 10")
            with col_download:
                csv_data = df_sorted[['title', 'year', 'cited_by_count', 'authors', 'journal', 'doi', 'abstract']].to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    "📥 전체 다운로드",
                    data=csv_data,
                    file_name=f"KeyPaper_{search_query[:15].replace(' ', '_')}.csv",
                    mime="text/csv",
                    help="검색된 전체 논문 데이터를 CSV 파일로 다운로드합니다. (제목, 연도, 인용수, 저자, 저널, DOI, 초록 포함)"
                )
            
            top10 = df_sorted.head(10).copy()
            top10['순위'] = range(1, len(top10) + 1)
            top10['인용'] = top10['cited_by_count'].apply(lambda x: f"{x:,}회")
            top10['논문'] = top10.apply(lambda r: f"{r['title']} ({r['year']})", axis=1)
            
            # 테이블 표시
            st.dataframe(
                top10[['순위', '인용', '논문']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "순위": st.column_config.NumberColumn("순위", width="small"),
                    "인용": st.column_config.TextColumn("인용", width="small"),
                    "논문": st.column_config.TextColumn("논문", width="large"),
                }
            )
            
            st.markdown("---")
            
            # 상세 정보
            st.markdown("#### 📄 상세 정보")
            for i, (_, row) in enumerate(df_sorted.head(10).iterrows(), 1):
                with st.expander(f"**{i}. {row['title']}** ({row['cited_by_count']:,}회 인용)"):
                    # DOI 링크
                    if row['doi']:
                        doi_url = row['doi'] if row['doi'].startswith('http') else f"https://doi.org/{row['doi']}"
                        st.markdown(f"🔗 **[논문 바로가기]({doi_url})**")
                    
                    st.markdown(f"""
                    - 📅 **출판연도:** {row['year']}년
                    - 📖 **저널:** {row['journal'] if row['journal'] else 'N/A'}
                    - 👥 **저자:** {row['authors'][:150]}{'...' if len(row['authors']) > 150 else ''}
                    """)
                    if row['abstract']:
                        st.markdown("**📝 초록:**")
                        st.write(row['abstract'][:600] + "..." if len(row['abstract']) > 600 else row['abstract'])
        
        # ========== 탭 2: 핵심 연구자 ==========
        with tab2:
            st.markdown("### 👥 핵심 연구자 (Key Players)")
            
            with st.spinner("연구자 네트워크 분석 중..."):
                top_degree, top_betweenness = calculate_author_centrality(df_sorted)
            
            if top_degree:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("#### 🎯 연결 중심성 Top 5")
                    st.caption("가장 많은 협업을 한 연구자")
                    
                    degree_df = pd.DataFrame([
                        {"순위": i+1, "연구자": name, "중심성": f"{score:.3f}"}
                        for i, (name, score) in enumerate(top_degree)
                    ])
                    st.dataframe(degree_df, use_container_width=True, hide_index=True)
                
                with col2:
                    st.markdown("#### 🌉 매개 중심성 Top 5")
                    st.caption("네트워크 연결자 역할")
                    
                    between_df = pd.DataFrame([
                        {"순위": i+1, "연구자": name, "중심성": f"{score:.3f}"}
                        for i, (name, score) in enumerate(top_betweenness)
                    ])
                    st.dataframe(between_df, use_container_width=True, hide_index=True)
                
                st.markdown("---")
                st.markdown("""
                **💡 해석 가이드:**
                - **연결 중심성**: 값이 높을수록 많은 연구자와 협업 (허브 역할)
                - **매개 중심성**: 값이 높을수록 서로 다른 연구 그룹을 연결 (브릿지 역할)
                """)
            else:
                st.info("분석할 공저 관계가 충분하지 않습니다.")
        
        # ========== 탭 3: 주요 저널 ==========
        with tab3:
            st.markdown("### 📚 주요 저널")
            
            # 저널별 논문 수 집계
            journal_counts = df_sorted['journal'].value_counts().head(15)
            journal_counts = journal_counts[journal_counts.index != '']  # 빈 저널 제외
            
            if len(journal_counts) > 0:
                journal_df = pd.DataFrame({
                    "순위": range(1, len(journal_counts) + 1),
                    "저널": journal_counts.index,
                    "논문 수": [f"{x}편" for x in journal_counts.values]
                })
                
                st.dataframe(journal_df, use_container_width=True, hide_index=True)
                
                st.markdown("---")
                st.markdown("#### 📊 저널별 논문 분포")
                st.bar_chart(journal_counts.head(10))
            else:
                st.info("저널 정보가 없습니다.")
    
    else:
        st.warning("검색 결과가 없습니다. 다른 검색어를 시도해 보세요.")

elif search_button and not search_query.strip():
    st.warning("검색어를 입력해 주세요!")

else:
    # 시작 화면
    st.markdown("""
    <h1 style="font-size: 3.5rem; font-weight: bold; color: #1e3a5f; text-align: center; margin-bottom: 0; padding-top: 1rem;">
        🔑 Key-Paper Helper
    </h1>
    <h2 style="font-size: 2rem; color: #555; text-align: center; margin-top: 0.5rem; margin-bottom: 1.5rem; font-weight: normal;">
        필독논문 찾기
    </h2>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div style="font-size: 1.1rem; color: #666; text-align: center; margin-bottom: 2rem;">
        키워드를 입력하면 필독논문 Top 10을 추천해 드려요.<br>
        <span style="color: #999; font-size: 0.9rem;">※ 영어 논문만 검색됩니다 (OpenAlex 데이터베이스 기반)</span>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    ### 🚀 사용 방법
    
    1. 🔍 **왼쪽**에서 검색어 입력
    2. 📅 **기간** 선택
    3. 🔎 **검색하기** 버튼 클릭!
    
    ---
    
    ### 💡 검색 팁
    
    | 검색 방법 | 예시 | 설명 |
    |----------|------|------|
    | 정확한 구문 | `"team science"` | 따옴표로 감싸면 정확히 일치 |
    | OR (또는) | `"AI" OR "machine learning"` | 둘 중 하나라도 포함 |
    | AND (그리고) | `"deep learning" AND "healthcare"` | 둘 다 포함 |
    
    ---
    
    ### ℹ️ 이 도구는?
    
    **작동 원리:**
    1. 입력한 키워드로 **OpenAlex** (세계 최대 학술 DB) 검색
    2. 검색된 논문들을 **인용 수** 순으로 정렬
    3. 가장 많이 인용된 **Top 10** 논문 추천!
    
    > 💬 "이 분야에서 가장 영향력 있는 논문이 뭐지?" 할 때 쓰세요!
    """)

# 푸터
st.divider()
st.markdown("""
<div style="text-align: center; color: #666; padding: 1rem 0;">
    <div style="font-size: 1.2rem; font-weight: bold; margin-bottom: 0.5rem;">
        🔑 Key-Paper Helper v3.5
    </div>
    <div style="font-size: 0.9rem; color: #888; margin-bottom: 0.8rem;">
        Powered by OpenAlex API | by 대학원생 MJ 🎓
    </div>
    <div style="font-size: 1rem; font-style: italic; color: #999; margin-bottom: 0.3rem;">
        "이 키워드로 뭘 먼저 읽어야 하지...?"
    </div>
    <div style="font-size: 0.85rem; color: #aaa;">
        구글 스칼라 10페이지째 헤매다가 만들었습니다 🫠
    </div>
</div>
""", unsafe_allow_html=True)
