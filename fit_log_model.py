import pandas as pd
import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter
import warnings

# Suppress math warnings raised during fitting
warnings.filterwarnings('ignore')

def model_func(x, a, b, c):
    """
    Fitted model with an epsilon guard against log(0)
    """
    return a + b * np.log(np.maximum(x + c, 1e-9))

def optimize_and_extract(input_csv, output_csv, x_col, y_col, target_r_squared=0.95):
    # 1. Load and preprocess
    df = pd.read_csv(input_csv)
    # Coerce to numeric and sort
    df[x_col] = pd.to_numeric(df[x_col], errors='coerce')
    df[y_col] = pd.to_numeric(df[y_col], errors='coerce')
    df = df.dropna(subset=[x_col, y_col]).sort_values(by=x_col).reset_index(drop=True)

    x_raw, y_raw = df[x_col].values, df[y_col].values

    # 2. Remove extreme outliers (MAD-based, more robust)
    median_y = np.median(y_raw)
    mad = np.median(np.abs(y_raw - median_y))
    if mad > 0:
        mask = np.abs(y_raw - median_y) < 5 * mad
        x_raw, y_raw = x_raw[mask], y_raw[mask]

    # 3. Define the search space
    # Smoothing windows are computed relative to the data length
    data_len = len(x_raw)
    smooth_windows = [w for w in [5, 11, 31, 51, 101] if w < data_len // 2]
    skip_steps = [1, 2, 5, 10, 20, 50]

    best_score = -np.inf
    best_res = None

    print(f"Optimizing, raw data points: {data_len}...")

    # 4. Nested-loop search for the best fit
    for sw in smooth_windows:
        y_smooth = savgol_filter(y_raw, window_length=sw, polyorder=2)

        for n_skip in skip_steps:
            x_s, y_s = x_raw[::n_skip], y_smooth[::n_skip]
            if len(x_s) < 8: continue

            try:
                # Better initial parameter guesses
                min_x = np.min(x_s)
                # The guess for c should keep x + c slightly above zero
                c_guess = -min_x + (np.max(x_s) - min_x) * 0.1 + 0.1
                p0 = [np.mean(y_s), (y_s[-1] - y_s[0]) or 1.0, c_guess]

                bounds = ([-np.inf, -np.inf, -min_x + 1e-7], [np.inf, np.inf, np.inf])

                popt, _ = curve_fit(model_func, x_s, y_s, p0=p0, bounds=bounds, maxfev=2000)

                # Score the fit
                y_pred = model_func(x_s, *popt)
                ss_res = np.sum((y_s - y_pred) ** 2)
                ss_tot = np.sum((y_s - np.mean(y_s)) ** 2)
                r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

                # Scoring: prefer high R^2 with as many points as possible
                # (guards against overfitting a handful of points)
                # score = R2 * log10(n_points)
                score = r2 * np.log10(len(x_s))

                if score > best_score:
                    best_score = score
                    best_res = {'x': x_s, 'y': y_s, 'p': popt, 'r2': r2, 'sw': sw, 'skip': n_skip}

            except:
                continue

    if not best_res:
        print("Fit failed. Check whether the data actually follows a logarithmic trend.")
        return

    # 5. Output the result
    p = best_res['p']
    print(f"--- Best result ---")
    print(f"Best R^2: {best_res['r2']:.4f} (smooth window: {best_res['sw']}, stride: {best_res['skip']})")
    print(f"Fitted model: y = {p[0]:.4f} + {p[1]:.4f} * ln(x + {p[2]:.4f})")

    df_out = pd.DataFrame({
        x_col: best_res['x'],
        y_col: best_res['y'],
        f'{y_col}_fitted': model_func(best_res['x'], *p)
    })
    df_out.to_csv(output_csv, index=False)
    return df_out

if __name__ == "__main__":
    # Example usage
    optimize_and_extract("your_data.csv", "optimized.csv", "time_s", "weight_g")
