import pandas as pd
import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import joblib

# Load CSV
df = pd.read_csv("telemetry_log.csv")

# Drop rows with missing or corrupt values
df = df.dropna()

# Define input features and output labels
input_features = ['speedX', 'speedY', 'speedZ', 'rpm', 'gear', 'trackPos', 'angle']
output_targets = ['accelerate', 'brake', 'steer']

X = df[input_features].values
y = df[output_targets].values

# Normalize input features
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# Split and train model
X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.1)

mlp = MLPRegressor(hidden_layer_sizes=(64, 64), activation='relu', solver='adam', max_iter=300)
mlp.fit(X_train, y_train)

# Save model and scaler
joblib.dump(mlp, "torcs_mlp_model.pkl")
joblib.dump(scaler, "input_scaler.pkl")

print("Model and scaler saved.")