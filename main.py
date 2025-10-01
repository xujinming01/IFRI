import streamlit as st
import pandas as pd
import tushare as ts
from datetime import datetime, timedelta

from utils import tushare_token

# --- Configuration ---
# PORTFOLIO = {
#     '沪深300ETF': '000300.SH',
#     '中证500ETF': '000905.SH',
#     # '创业板ETF': '399006.SZ',
#     # '科创50ETF': '000688.SH',
# }
PORTFOLIO = {
    'A500ETF': {'指数代码': '000510.SH', 'ETF代码': '512050'},
    # '创业板50ETF': {'指数代码': '399673.SZ', 'ETF代码': '159949'},
}

# --- Core Functions ---

# use st.cache_data to avoid repeated API requests
# ttl=3600 means cache for 1 hour (3600 seconds), which is sufficient for weekly investment
@st.cache_data(ttl=3600)
def get_valuation_data(token, portfolio):
    """
    Fetches PE-TTM and PB valuation data from Tushare for multiple historical periods.

    Args:
        token (str): Your Tushare API token.
        portfolio (dict): A dictionary of ETF names and their corresponding index codes.

    Returns:
        pandas.DataFrame: A DataFrame containing current valuations and historical percentiles.
    """
    try:
        ts.set_token(token)
        pro = ts.pro_api()
        
        end_date = datetime.now().strftime('%Y%m%d')
        # Fetch 10 years of data to cover all required periods
        start_date = (datetime.now() - timedelta(days=365 * 10)).strftime('%Y%m%d')

        results = []
        
        progress_bar = st.progress(0, text="Initializing...")
        total_indices = len(portfolio)

        for i, (name, details) in enumerate(portfolio.items()):
            index_code = details['指数代码']
            etf_code = details['ETF代码']

            progress_text = f"Fetching valuation data for {name} ({index_code})..."
            progress_bar.progress((i + 1) / total_indices, text=progress_text)
            
            # Fetch historical valuation data for both PE and PB
            df_hist = pro.index_dailybasic(
                ts_code=index_code,
                start_date=start_date,
                end_date=end_date,
                fields='ts_code,trade_date,pe_ttm,pb'
            )
            df_hist['trade_date'] = pd.to_datetime(df_hist['trade_date'])

            if df_hist.empty:
                st.warning(f"无法获取有效的历史数据 {name} ({index_code})。跳过该项。")
                continue

            current_pe = df_hist.iloc[0]['pe_ttm']
            current_pb = df_hist.iloc[0]['pb']

            item_result = {
                'ETF名称': name,
                '跟踪指数': index_code,
                '代码': etf_code,
                '当前PE-TTM': f"{current_pe:.2f}",
                '当前PB': f"{current_pb:.2f}"
            }

            # Calculate percentiles for 3, 5, and 10-year periods
            for years in [3, 5, 10]:
                start_period = datetime.now() - timedelta(days=365 * years)
                df_period = df_hist[df_hist['trade_date'] >= start_period]

                # Clean PE data and calculate percentile
                df_pe = df_period.dropna(subset=['pe_ttm'])
                df_pe = df_pe[df_pe['pe_ttm'] > 0]
                if not df_pe.empty:
                    pe_percentile = (df_pe['pe_ttm'] < current_pe).sum() / len(df_pe) * 100
                    item_result[f'PE分位({years}年)'] = f"{pe_percentile:.2f}%"
                else:
                    item_result[f'PE分位({years}年)'] = "N/A"

                # Clean PB data and calculate percentile
                df_pb = df_period.dropna(subset=['pb'])
                df_pb = df_pb[df_pb['pb'] > 0]
                if not df_pb.empty:
                    pb_percentile = (df_pb['pb'] < current_pb).sum() / len(df_pb) * 100
                    item_result[f'PB分位({years}年)'] = f"{pb_percentile:.2f}%"
                else:
                    item_result[f'PB分位({years}年)'] = "N/A"
            
            results.append(item_result)
        
        progress_bar.empty()
        return pd.DataFrame(results)

    except Exception as e:
        st.error(f"数据获取失败，请检查你的Tushare Token是否正确或网络连接。错误信息: {e}")
        return pd.DataFrame()


def calculate_allocation(total_investment, valuation_data, selected_percentile_col):
    """
    Calculates investment weight and amount based on the selected valuation percentile.

    Args:
        total_investment (float): The total amount to invest.
        valuation_data (pandas.DataFrame): The DataFrame with valuation percentiles.
        selected_percentile_col (str): The column name of the chosen percentile for calculation.

    Returns:
        pandas.DataFrame: A DataFrame with the final investment advice.
    """
    if valuation_data.empty or selected_percentile_col not in valuation_data.columns:
        return pd.DataFrame()

    # --- Core Investment Strategy ---
    # You can modify the weighting rules here based on your investment philosophy
    def get_weight(percentile_str):
        if not isinstance(percentile_str, str) or '%' not in percentile_str:
            return 0 # Return 0 weight if data is not available
        percentile = float(percentile_str.strip('%'))
        if percentile < 20:
            return 2.0  # Extremely undervalued, weight x2.0
        elif 20 <= percentile < 40:
            return 1.5  # Undervalued, weight x1.5
        elif 40 <= percentile < 60:
            return 1.0  # Fairly valued, weight x1.0
        elif 60 <= percentile < 80:
            return 0.5  # Overvalued, weight x0.5
        else:
            return 0.1  # Extremely overvalued, weight x0.1

    df = valuation_data.copy()
    df['投资权重'] = df[selected_percentile_col].apply(get_weight)
    
    total_weight = df['投资权重'].sum()
    
    if total_weight == 0:
        st.warning("所有指数均处于极度高估状态，根据策略本期不进行投资。")
        df['建议投资额(元)'] = 0
        return df

    df['建议投资额(元)'] = (df['投资权重'] / total_weight * total_investment).round(2)
    
    return df

# --- Streamlit UI ---
st.set_page_config(page_title="Jaime's Investment Tool", page_icon="📈", layout="wide")
st.title("📈 Jaime's Investment Tool")
st.caption("一个根据指数估值动态计算定投金额的助手")

st.subheader("1. 输入本期总投资金额")
total_investment = st.number_input("计划总投资金额 (CNY)", min_value=0.0, step=100.0, format="%.2f", value=1000.0)

if total_investment > 0:
    valuation_data = get_valuation_data(tushare_token, PORTFOLIO)

    if not valuation_data.empty:
        st.subheader("2. 最新指数估值概览")
        # Define the desired column order for the overview table
        column_order = [
            'ETF名称', '跟踪指数',
            '当前PB',
            'PB分位(3年)', 'PB分位(5年)', 'PB分位(10年)',
            '当前PE-TTM',
            'PE分位(3年)', 'PE分位(5年)', 'PE分位(10年)',
        ]
        # Filter for columns that actually exist in the dataframe to prevent errors
        display_columns = [col for col in column_order if col in valuation_data.columns]
        st.dataframe(valuation_data[display_columns], use_container_width=True, hide_index=True)

        st.subheader("3. 本周投资建议")
        col1, col2 = st.columns(2)
        with col1:
            valuation_metric = st.selectbox("选择估值指标:", ('PB', 'PE-TTM'))
        with col2:
            history_period = st.selectbox("选择参考周期:", ('3年', '5年', '10年'))

        # Determine the column to use for allocation calculation
        metric_prefix = 'PE' if valuation_metric == 'PE-TTM' else 'PB'
        selected_col = f'{metric_prefix}分位({history_period})'

        allocation_result = calculate_allocation(total_investment, valuation_data, selected_col)

        if not allocation_result.empty:
            # Format the output for better readability
            display_df = allocation_result.rename(columns={
                selected_col: f'参考分位({metric_prefix})',
                '建议投资额(元)': '建议投资额'
            })
            
            st.data_editor(
                display_df[['ETF名称', '代码', f'参考分位({metric_prefix})', '投资权重', '建议投资额']],
                use_container_width=True,
                disabled=True,
                hide_index=True,
            )

            actual_total = allocation_result['建议投资额(元)'].sum()
            st.metric(label="总投资金额", value=f"¥ {actual_total:.2f}")
