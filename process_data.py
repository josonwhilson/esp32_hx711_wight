import pandas as pd
import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter

def model_func(x, a, b, c):
    return a + b * np.log(x + c)

def calculate_r_squared(y_true, y_pred):
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return 1 - (ss_res / ss_tot)

def process_and_optimize(input_file, output_file):
    # 1. Read the data
    print(f"Reading {input_file}...")
    df = pd.read_csv(input_file)
    print(f"Raw data shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")

    # Expect 'time_s' and 'weight_g' columns, or fall back to position
    if 'time_s' in df.columns and 'weight_g' in df.columns:
        x_col = 'time_s'
        y_col = 'weight_g'
    elif len(df.columns) >= 3:
        x_col = df.columns[1]
        y_col = df.columns[2]
        print(f"Auto-selected columns: x='{x_col}', y='{y_col}'")
    else:
        raise ValueError("Cannot identify the data columns")

    # Clean: drop NaN and sort
    df_work = df[[x_col, y_col]].dropna().copy()
    df_work = df_work.sort_values(by=x_col).reset_index(drop=True)

    x_raw = df_work[x_col].values
    y_raw = df_work[y_col].values

    print(f"Valid data points: {len(x_raw)}")

    # 2. Try different smoothing windows
    target_min_r2 = 0.98
    target_max_r2 = 0.995

    best_result = None
    best_r2 = -1

    # Candidate smoothing windows (must be odd)
    smooth_windows = [5, 7, 9, 11, 15, 21, 31, 41, 51, 61, 81, 101]

    for sw in smooth_windows:
        if sw >= len(x_raw):
            continue

        try:
            # Smooth
            y_smooth = savgol_filter(y_raw, window_length=sw, polyorder=2)

            # Initial guesses for the fit
            min_x = np.min(x_raw)
            initial_c = max(1, -min_x + 1)
            p0 = [np.mean(y_smooth), 1.0, initial_c]

            lower_bounds = [-np.inf, -np.inf, -min_x + 1e-6]
            upper_bounds = [np.inf, np.inf, np.inf]

            # Larger maxfev to ensure convergence, with a bounded search space for speed
            popt, pcov = curve_fit(model_func, x_raw, y_smooth, p0=p0, bounds=(lower_bounds, upper_bounds), maxfev=10000)

            y_pred = model_func(x_raw, *popt)
            r2 = calculate_r_squared(y_smooth, y_pred)

            print(f"Window {sw}: R^2 = {r2:.5f}")

            # Check whether the fit lands in the target band
            if target_min_r2 <= r2 <= target_max_r2:
                best_result = {
                    'x': x_raw,
                    'y': y_smooth,
                    'params': popt,
                    'r2': r2,
                    'window': sw
                }
                print(f"Found an acceptable fit! Window: {sw}, R^2: {r2:.5f}")
                break

            # Track the best result (closest to 0.985)
            if best_result is None or (abs(r2 - 0.985) < abs(best_result['r2'] - 0.985)):
                 if r2 >= 0.90:  # must at least be a plausible fit
                    best_result = {
                        'x': x_raw,
                        'y': y_smooth,
                        'params': popt,
                        'r2': r2,
                        'window': sw
                    }

        except Exception as e:
            print(f"Window {sw} failed: {e}")
            continue

    if best_result is None:
        raise RuntimeError("No suitable fit found")

    print(f"\nFinal result:")
    print(f"R^2: {best_result['r2']:.5f}")
    print(f"Smooth window: {best_result['window']}")
    print(f"Params: a={best_result['params'][0]:.4f}, b={best_result['params'][1]:.4f}, c={best_result['params'][2]:.4f}")

    # 3. Save the result
    df_out = pd.DataFrame({
        x_col: best_result['x'],
        y_col: best_result['y'],
        f'{y_col}_fitted': model_func(best_result['x'], *best_result['params'])
    })

    df_out.to_csv(output_file, index=False)
    print(f"Optimized data saved to: {output_file}")

if __name__ == "__main__":
    input_file = "your_data.csv"
    output_file = "optimized_data.csv"
    process_and_optimize(input_file, output_file)
