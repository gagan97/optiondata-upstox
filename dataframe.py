import time
import pandas as pd
import polars as pl
import dask.dataframe as dd
import vaex

# Create a sample DataFrame (1 million rows)
N = 10**6
data = {
    "col1": range(N),
    "col2": [x * 2 for x in range(N)],
    "col3": [x % 10 for x in range(N)],
}

# Function to test performance for Pandas
def test_pandas():
    df = pd.DataFrame(data)
    start_time = time.time()
    result = df[df['col1'] > 100]
    result = result.groupby('col3').agg({'col2': 'sum'})
    end_time = time.time()
    return end_time - start_time

# Function to test performance for Polars
def test_polars():
    df = pl.DataFrame(data)
    start_time = time.time()
    result = df.filter(pl.col('col1') > 100)
    result = result.groupby('col3').agg(pl.col('col2').sum())
    end_time = time.time()
    return end_time - start_time

# Function to test performance for Dask
def test_dask():
    df = dd.from_pandas(pd.DataFrame(data), npartitions=4)
    start_time = time.time()
    result = df[df['col1'] > 100]
    result = result.groupby('col3').agg({'col2': 'sum'})
    result.compute()  # Trigger computation
    end_time = time.time()
    return end_time - start_time

# Function to test performance for Vaex
def test_vaex():
    df = vaex.from_pandas(pd.DataFrame(data))
    start_time = time.time()
    result = df[df.col1 > 100]
    result = result.groupby('col3', agg={'col2': 'sum'})
    result = result.to_pandas()  # Convert to pandas to finish the operation
    end_time = time.time()
    return end_time - start_time

# Running all tests and displaying results
def run_tests():
    print(f"{'Library':<10} {'Time (seconds)'}")
    print("-" * 30)
    
    pandas_time = test_pandas()
    print(f"{'Pandas':<10} {pandas_time:.4f}")
    
    polars_time = test_polars()
    print(f"{'Polars':<10} {polars_time:.4f}")
    
    dask_time = test_dask()
    print(f"{'Dask':<10} {dask_time:.4f}")
    
    vaex_time = test_vaex()
    print(f"{'Vaex':<10} {vaex_time:.4f}")

# Execute the test
run_tests()
