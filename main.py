import streamlit as st
import pandas as pd
import tushare as ts
from datetime import datetime, timedelta

from utils import tushare_token

# --- 配置区 ---
PORTFOLIO = {
    '沪深300ETF': '000300.SH',
    '中证500ETF': '000905.SH',
    '创业板ETF': '399006.SZ',
    '科创50ETF': '000688.SH',
}

# --- 核心功能函数 ---

# 使用Streamlit的缓存功能，避免重复请求API
# ttl=3600 表示缓存1小时 (3600秒)，对于周定投来说足够了
@st.cache_data(ttl=3600)
def get_valuation_data(tushare_token, portfolio, history_years=10):
    """
    从Tushare获取指数的PE-TTM估值，并计算当前估值在历史数据中的百分位。

    Args:
        tushare_token (str): 你的Tushare API token.
        portfolio (dict): 包含ETF名称和对应指数代码的字典.
        history_years (int): 用于计算估值百分位的历史年限.

    Returns:
        pandas.DataFrame: 包含估值数据和百分位的DataFrame.
    """
    try:
        ts.set_token(tushare_token)
        pro = ts.pro_api()
        
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=365 * history_years)).strftime('%Y%m%d')

        results = []
        
        # 使用st.progress来显示数据加载进度
        progress_bar = st.progress(0, text="正在初始化...")
        total_indices = len(portfolio)

        for i, (name, code) in enumerate(portfolio.items()):
            progress_text = f"正在获取 {name} ({code}) 的估值数据..."
            progress_bar.progress((i + 1) / total_indices, text=progress_text)
            
            # 获取历史估值数据
            df = pro.index_dailybasic(
                ts_code=code,
                start_date=start_date,
                end_date=end_date,
                fields='ts_code,trade_date,pe_ttm'
            )
            
            # 数据清洗，去除PE为负或空值的情况
            df = df.dropna(subset=['pe_ttm'])
            df = df[df['pe_ttm'] > 0]
            
            if df.empty:
                st.warning(f"未能获取到 {name} ({code}) 的有效历史估值数据，已跳过。")
                continue

            # 获取最新估值
            current_pe = df.iloc[0]['pe_ttm']
            
            # 计算估值百分位
            # 百分位 = (历史数据中比当前值小的天数 / 总天数) * 100
            percentile = (df['pe_ttm'] < current_pe).sum() / len(df) * 100
            
            results.append({
                'ETF名称': name,
                '跟踪指数': code,
                '当前PE-TTM': f"{current_pe:.2f}",
                '估值分位': f"{percentile:.2f}%"
            })
        
        progress_bar.empty() # 完成后移除进度条
        return pd.DataFrame(results)

    except Exception as e:
        st.error(f"数据获取失败，请检查你的Tushare Token是否正确或网络连接。错误信息: {e}")
        return pd.DataFrame()


def calculate_allocation(total_investment, valuation_data):
    """
    根据估值百分位决定投资权重和金额。

    Args:
        total_investment (float): 计划投资的总金额.
        valuation_data (pandas.DataFrame): 包含估值分位的DataFrame.

    Returns:
        pandas.DataFrame: 包含最终投资建议的DataFrame.
    """
    if valuation_data.empty:
        return pd.DataFrame()

    # --- 投资策略核心 ---
    # 你可以根据自己的投资哲学，随意修改这里的权重规则
    def get_weight(percentile_str):
        percentile = float(percentile_str.strip('%'))
        if percentile < 20:
            return 2.0  # 极度低估，权重x2.0
        elif 20 <= percentile < 40:
            return 1.5  # 偏低估，权重x1.5
        elif 40 <= percentile < 60:
            return 1.0  # 正常估值，权重x1.0
        elif 60 <= percentile < 80:
            return 0.5  # 偏高估，权重x0.5
        else:
            return 0.1  # 极度高估，权重x0.1 (少量持有或不投)

    df = valuation_data.copy()
    df['投资权重'] = df['估值分位'].apply(get_weight)
    
    total_weight = df['投资权重'].sum()
    
    if total_weight == 0:
        st.warning("所有指数均处于极度高估状态，根据策略本期不进行投资。")
        df['建议投资额(元)'] = 0
        return df

    # 根据权重计算每部分的投资额
    df['建议投资额(元)'] = (df['投资权重'] / total_weight * total_investment).round(2)
    
    return df

# --- Streamlit 界面代码 ---
st.set_page_config(page_title="Jaime's Investment Tool", page_icon="📈")
st.title("📈 Jaime's Investment Tool")
st.caption("一个根据指数估值动态计算定投金额的助手")

# 在侧边栏让用户输入Tushare Token
with st.sidebar:
    st.header("配置")
    tushare_token = st.text_input("请输入你的 Tushare Token", type="password")
    st.markdown("[如何获取Tushare Token?](https://tushare.pro/document/1?doc_id=39)")
    st.info("你的Token只在本次会话中有效，我们不会存储它。")

# 主界面
if not tushare_token:
    st.warning("👈 请在左侧侧边栏输入你的 Tushare Token 以开始。")
else:
    st.subheader("1. 输入本期定投总额")
    total_investment = st.number_input("计划投资总额(元)", min_value=0.0, step=100.0, format="%.2f")

    if st.button("🚀 开始计算", use_container_width=True):
        if total_investment > 0:
            # 1. 调用函数获取最新的估值数据
            valuation_data = get_valuation_data(tushare_token, PORTFOLIO)

            if not valuation_data.empty:
                st.subheader("2. 最新指数估值概览")
                st.dataframe(valuation_data, use_container_width=True)
                
                # 2. 调用策略函数计算分配额
                allocation_result = calculate_allocation(total_investment, valuation_data)

                if not allocation_result.empty:
                    st.subheader("3. 本周投资建议")
                    st.success("计算完成！请参考以下投资配额：")
                    
                    # 格式化输出，让表格更好看
                    display_df = allocation_result.rename(columns={
                        '估值分位': '估值分位(PE)',
                        '建议投资额(元)': '建议投资额'
                    })
                    
                    # 使用st.data_editor来展示，更美观
                    st.data_editor(
                        display_df[['ETF名称', '跟踪指数', '估值分位(PE)', '投资权重', '建议投资额']],
                        use_container_width=True,
                        disabled=True, # 设置为只读
                        hide_index=True,
                    )

                    # 计算并显示总计
                    actual_total = allocation_result['建议投资额(元)'].sum()
                    st.metric(label="合计投资额", value=f"¥ {actual_total:.2f}")

        else:
            st.warning("请输入一个大于0的投资额。")

