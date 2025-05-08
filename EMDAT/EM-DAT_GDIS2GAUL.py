import pandas as pd
import json
import xml.etree.ElementTree as ET
from xml.dom import minidom

###############################################################################
# 1) Define File Paths
###############################################################################
file_path = 'D:/ProjDB/EMDAT/public_emdat_GDIS_aligned.xlsx'

# GAUL Level-2 XML (for extracting FID_2)
xml_file_path_2 = 'D:/ProjDB/GAUL/g2015_2014_2.xml'

# GAUL Level-1 XML (for extracting FID_1)
xml_file_path_1 = 'D:/ProjDB/GAUL/g2015_2014_1.xml'

# Final extracted files
extracted_file_path_2 = 'D:/ProjDB/GAUL/g2015_2014_2_GeomExtract.xml'
extracted_file_path_1 = 'D:/ProjDB/GAUL/g2015_2014_1_GeomExtract.xml'

# Final modified Excel file
output_file_path = 'D:/ProjDB/GAUL/public_emdat_GDIS_GAUL_aligned.xlsx'

###############################################################################
# 2) Helper Function: Extract Administrative Units from JSON
###############################################################################
def extract_admin_units(row):
    """
    Extracts adm1/adm2 codes and names from the JSON in 'Admin Units'.
    Handles both dictionary-based and list-based JSON.
    If JSON is invalid or structure is unexpected, fills columns with None.
    """
    try:
        admin_units = json.loads(row['Admin Units'])

        if isinstance(admin_units, dict):
            row['adm1_code'] = admin_units.get('adm1_code')
            row['adm1_name'] = admin_units.get('adm1_name')
            row['adm2_code'] = admin_units.get('adm2_code')
            row['adm2_name'] = admin_units.get('adm2_name')

        elif isinstance(admin_units, list) and len(admin_units) > 0 and isinstance(admin_units[0], dict):
            first_item = admin_units[0]
            row['adm1_code'] = first_item.get('adm1_code')
            row['adm1_name'] = first_item.get('adm1_name')
            row['adm2_code'] = first_item.get('adm2_code')
            row['adm2_name'] = first_item.get('adm2_name')
        else:
            row['adm1_code'] = None
            row['adm1_name'] = None
            row['adm2_code'] = None
            row['adm2_name'] = None

    except json.JSONDecodeError:
        row['adm1_code'] = None
        row['adm1_name'] = None
        row['adm2_code'] = None
        row['adm2_name'] = None

    return row

###############################################################################
# 3) Load Excel File and Apply Transformation
###############################################################################
df = pd.read_excel(file_path)

# Apply the function to extract admin units
df = df.apply(extract_admin_units, axis=1)

# Optionally, set data types for new columns
df = df.astype({
    'adm1_code': 'Int64',  # 'Int64' allows integer + NaN
    'adm1_name': 'str',
    'adm2_code': 'Int64',
    'adm2_name': 'str'
})

###############################################################################
# 4) Define XML Namespaces
###############################################################################
namespaces = {
    'gml':  'http://www.opengis.net/gml',
    'gaul': 'http://www.fao.org/tempref/AG/Reserved/PPLPF/ftpOUT/GLiPHA/Gaulmaps/gaul_2008/documentation/GAUL%20Doc01%20Ver16.pdf',
    'wfs':  'http://www.opengis.net/wfs',
    'xs':   'http://www.w3.org/2001/XMLSchema',
    'xsi':  'http://www.w3.org/2001/XMLSchema-instance'
}
for prefix, uri in namespaces.items():
    ET.register_namespace(prefix, uri)

###############################################################################
# 5) Extract Unique Features from GAUL Level-2 XML
###############################################################################
tree_2 = ET.parse(xml_file_path_2)
root_2 = tree_2.getroot()

new_root_2 = ET.Element(root_2.tag)
added_features_2 = set()  # Track unique features to prevent duplicates

for _, row in df.iterrows():
    if pd.notnull(row['adm2_code']) and pd.notnull(row['adm2_name']):
        xpath_query = f".//gaul:adm2_code[.='{row['adm2_code']}']/.."
        matching_features = root_2.findall(xpath_query, namespaces=namespaces)

        if not matching_features:
            xpath_query = f".//gaul:adm2_name[.='{row['adm2_name']}']/.."
            matching_features = root_2.findall(xpath_query, namespaces=namespaces)

        for feature in matching_features:
            feature_id = feature.find('.//gaul:FID', namespaces=namespaces)
            if feature_id is not None:
                feature_id_text = feature_id.text

                if feature_id_text not in added_features_2:
                    new_root_2.append(feature)
                    added_features_2.add(feature_id_text)

new_root_2.set('numberOfFeatures', str(len(added_features_2)))
ET.ElementTree(new_root_2).write(extracted_file_path_2, encoding='UTF-8', xml_declaration=True)
print(f'Matched features saved to {extracted_file_path_2}')

###############################################################################
# 6) Extract Unique Features from GAUL Level-1 XML
###############################################################################
tree_1 = ET.parse(xml_file_path_1)
root_1 = tree_1.getroot()

new_root_1 = ET.Element(root_1.tag)
added_features_1 = set()  # Track unique features to prevent duplicates

for _, row in df.iterrows():
    if pd.notnull(row['adm1_code']) and pd.notnull(row['adm1_name']):
        xpath_query = f".//gaul:adm1_code[.='{row['adm1_code']}']/.."
        matching_features = root_1.findall(xpath_query, namespaces=namespaces)

        if not matching_features:
            xpath_query = f".//gaul:adm1_name[.='{row['adm1_name']}']/.."
            matching_features = root_1.findall(xpath_query, namespaces=namespaces)

        for feature in matching_features:
            feature_id = feature.find('.//gaul:FID', namespaces=namespaces)
            if feature_id is not None:
                feature_id_text = feature_id.text

                if feature_id_text not in added_features_1:
                    new_root_1.append(feature)
                    added_features_1.add(feature_id_text)

new_root_1.set('numberOfFeatures', str(len(added_features_1)))
ET.ElementTree(new_root_1).write(extracted_file_path_1, encoding='UTF-8', xml_declaration=True)
print(f'Matched features saved to {extracted_file_path_1}')

###############################################################################
# 7) Save the Final DataFrame with Extracted Information
###############################################################################
df.to_excel(output_file_path, index=False)
print(f"Final file saved with extracted information: {output_file_path}")