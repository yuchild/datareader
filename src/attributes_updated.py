import numpy as np
from numpy import where
import pandas as pd
from pandas import concat
import matplotlib.pyplot as plt
plt.style.use('fivethirtyeight')
import seaborn as sns

import pandas_datareader.data as pdr
import yfinance as yf
yf.pdr_override()

from datetime import datetime

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV
import joblib

from sklearn.metrics import (roc_auc_score
                             , precision_score
                             , recall_score
                             , roc_curve
                             , confusion_matrix
                             , plot_confusion_matrix
                             , precision_recall_curve
                             , auc
                            )

from sklearn.utils import resample
from sklearn.model_selection import cross_val_score

# take about a minute
def get_tables(start_dates):
    for x in start_dates:
        stock_df = pdr.get_data_yahoo(x.upper()
                                      , data_source ='yahoo'
                                      , start = datetime.strptime(start_dates[x], '%m/%d/%Y')
                                      , end = datetime.strptime(datetime.today().strftime('%m/%d/%Y'), '%m/%d/%Y')
                                     )
        stock_df.to_pickle(f'./data/{x}_df.pkl')
        
def data(stock, start_date, days_ahead):
    """
    Inputs: stock, string of stock symbol
            start_date, string of stock origination date in form 'MM/DD/YYYY'
            days_ahead, int days prediction ahead, 1 for 1 day ahead, 2 for 2 days ahead, etc...
    Output: X_train, X_test, y_train, y_test for modeling
    """
  
    # download daily stock data from yahoo 
    stock_df = pd.read_pickle(f'./data/{stock}_df.pkl')
    
    # some open values are 0.0, set it same as close value
    stock_df['Open'] = where(stock_df['Open'] == 0.0, stock_df['Close'], stock_df['Open'])
    
    # open close % difference
    stock_df['oc'] = (stock_df.Open - stock_df.Close) / (stock_df.Open)
    
    # high low % difference
    stock_df['hl'] = (stock_df.High - stock_df.Low) / (stock_df.Low)
    
    # adjusted close % change from previous day
    stock_df['adj'] = stock_df['Adj Close'].pct_change()
    
    # 7 day standard deviation of adjusted close % change from previous day 
    stock_df['21stdev_adj'] = stock_df.adj.rolling(21).std()
    
    # 7 day rolling average of adjusted close % change from pervious day
    stock_df['21sma_adj'] = stock_df.adj.rolling(21).mean()
    
    # Direction
    stock_df['direction'] = where(stock_df['adj'].shift(-days_ahead) > stock_df['adj'], 1, -1)
    
    # drop nulls
    stock_df.dropna(axis=0, inplace=True)    
    
    # split stock_df to train test dataframes
    split = int(stock_df.shape[0] * 0.85)
    train = stock_df[:split]
    test = stock_df[split:]
    
    # upsample class inbalance for 'direction' 
    train_major = train[train['direction'] == -1]
    train_minor = train[train['direction'] == 1]

    train_minor_upsampled = resample(train_minor
                                     , replace = True
                                     , n_samples = train_major.shape[0]
                                     , random_state = 42
                                    )

    train_upsampled = concat([train_major, train_minor_upsampled])
    
    # shuffle the train dataframe to mix up the order to train model
    train = train_upsampled.sample(frac=1).reset_index(drop=True)
    
    # features
    features = ['oc'
               , 'hl'
               , '21stdev_adj'
               , '21sma_adj'
              ]
    
    # X_train, X_test, y_train, y_test
    X_train = train[features]
    y_train = train['direction']
    
    X_test = test[features]
    y_test = test['direction']
    
    return X_train, X_test, y_train, y_test, stock_df

def returns_plot(stock_name, stock_df, rfc_model, y_test):
    """
    Creates plot of model returns from 100% or 1.
    
    Inputs: stock_name, str of stock ticker symbol
            stock_df, pandas dataframe of stock from data() function above
            rfc_model, sklearn random forest classifier model
            y_test, pandas series of target test data used to find number of test values
    Outputs: None, graph of model returns
    """
    stock_df['prediction'] = rfc_model.predict(stock_df[['oc', 'hl', '21stdev_adj', '21sma_adj']])
    stock_df['returns'] = stock_df['adj'].shift(-1, fill_value = stock_df['adj'].median()) * stock_df['prediction']
    
    test_length = len(y_test)
    (stock_df['returns'][-test_length:] + 1).cumprod().plot()
    plt.title(f'{stock_name} Expected Returns %');

def all_func(stock_name, start_date, days_ahead, model_name, days_back):
    """
    All function call to output desired predictions and metrics
    
    Inputs: stock_name, str of stock ticker symbol
            start_date, str of stock start date ipo
            days_ahead, int of 1, 3, or 5 days ahead
            model_name, str of model used for graphs use only
            days_back, int of days back, 1 to use today for tomorrow's predicition
    Outputs: None: roc, precision recall curves, and confusion matrix grphas
             print out of str sentence of model days ahead drediction, model return, and stock return   
    """
    
    X_train, X_test, y_train, y_test, stock_df = data(stock_name, start_date, days_ahead)
    
    rfc_model, y_pred, y_probs = rfc(X_train, X_test, y_train, stock_name, days_ahead)
    
    returns_plot(stock_name, stock_df, rfc_model, y_test)
    
    roc_plot(y_test, y_probs, stock_name, model_name)
    
    prec_recall(y_test, y_probs, stock_name, model_name)
    
    confusion_matrix(rfc_model, X_test, y_test, stock_name)
    
    last = stock_df[['oc', 'hl', '21stdev_adj', '21sma_adj']].iloc[-days_back]
    test_length = len(y_test)
    
    returns_on_ones = []
    for idx in range(-test_length, 0):
        if stock_df['prediction'][idx] == 1:
            returns_on_ones.append(1 + stock_df['returns'][idx])

    returns = 1
    for x in returns_on_ones:
        returns *= x
    
    test_idx = int(len(stock_df)*0.85)
    stock_returns = (stock_df['Close'][-1] - stock_df['Close'][-test_idx]) / stock_df['Close'][-test_idx]
    
    if rfc_model.predict(np.array(last).reshape(1, -1))[0] == 1:
        return print(f'Buy {stock_name} {days_ahead} day(s) ahead\nModel Returns (x 100 for %): {round(returns, 4)}\nStock Returns (x 100 for %): {round(stock_returns, 4)}')
    else:
        return print(f'Sell or hold {stock_name} {days_ahead} day(s) ahead\nModel Returns (x 100 for %): {round(returns, 4)}\nStock Returns (x 100 for %): {round(stock_returns, 4)}')