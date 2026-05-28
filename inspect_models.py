import pickle, warnings
warnings.filterwarnings('ignore')

base = "C:/Apps/pRDEICTIEV mIANTENANCE/EDR_ML/models"

with open(base + "/feature_cols.pkl","rb") as f:
    features = pickle.load(f)
print("FEATURE COLS:", features)
print("Count:", len(features))

with open(base + "/label_encoder.pkl","rb") as f:
    le = pickle.load(f)
print("\nLABEL ENCODER classes:", le.classes_)

with open(base + "/classifier.pkl","rb") as f:
    clf = pickle.load(f)
print("\nCLASSIFIER type:", type(clf).__name__)
try:
    print("  n_features_in_:", clf.n_features_in_)
except: pass

with open(base + "/regressor.pkl","rb") as f:
    reg = pickle.load(f)
print("\nREGRESSOR type:", type(reg).__name__)
try:
    print("  n_features_in_:", reg.n_features_in_)
except: pass

print("\nAll models loaded successfully.")
