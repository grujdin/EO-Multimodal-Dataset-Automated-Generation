import pandas as pd
import xml.etree.ElementTree as ET
import os

###############################################################################
# 1) Define file paths
###############################################################################
HOME_DIR = r"path/to/your/home/directory"
excel_file_path = os.path.join(HOME_DIR, "data", "emdat_obs2gaul.xlsx")

# GAUL Level-2 XML (for FID_2)
xml_file_path_2 = os.path.join(HOME_DIR, "Data", "g2015_2014_2_geom_extract.xml")

# GAUL Level-1 XML (for FID_1)
xml_file_path_1 = os.path.join(HOME_DIR, "Data", "g2015_2014_1_geom_extract.xml")

# Final single output (with both FID_1 and FID_2 columns)
output_file_path = os.path.join(HOME_DIR, "Data", "emdat_obs2gaul_geom.xlsx")

###############################################################################
# 2) Load Excel file into DataFrame
###############################################################################
df = pd.read_excel(excel_file_path)

###############################################################################
# 3) Register XML namespaces (required for XPath lookups)
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
# 4) Extract FID_2 from GAUL Level-2 XML
###############################################################################
tree_2 = ET.parse(xml_file_path_2)
root_2 = tree_2.getroot()

fids_2 = []
for _, row in df.iterrows():
    fid_2 = None  # Default if no match found

    # Check that row has adm2_code and adm2_name
    if pd.notnull(row.get('adm2_code')) and pd.notnull(row.get('adm2_name')):
        # Convert to string and escape any double quotes
        escaped_adm2_code = str(row['adm2_code']).replace('"', '\\"')
        escaped_adm2_name = str(row['adm2_name']).replace('"', '\\"')

        # Try matching by adm2_code first (using double quotes in the XPath)
        xpath_query = f'.//gaul:adm2_code[.="{escaped_adm2_code}"]/..'
        matching_features = root_2.findall(xpath_query, namespaces=namespaces)

        # If no match, try adm2_name
        if not matching_features:
            xpath_query = f'.//gaul:adm2_name[.="{escaped_adm2_name}"]/..'
            matching_features = root_2.findall(xpath_query, namespaces=namespaces)

        # If we have matches, take the first one's gaul:FID
        for feature in matching_features:
            fid_element = feature.find('.//gaul:FID', namespaces=namespaces)
            if fid_element is not None:
                fid_2 = fid_element.text
            break  # Only the first match
    fids_2.append(fid_2)

df['FID_2'] = fids_2  # Add column for FID_2

###############################################################################
# 5) Extract FID_1 from GAUL Level-1 XML
###############################################################################
tree_1 = ET.parse(xml_file_path_1)
root_1 = tree_1.getroot()

fids_1 = []
for _, row in df.iterrows():
    fid_1 = None  # Default if no match found

    # Check that row has adm1_code and adm1_name
    if pd.notnull(row.get('adm1_code')) and pd.notnull(row.get('adm1_name')):
        # Convert to string and escape any double quotes
        escaped_adm1_code = str(row['adm1_code']).replace('"', '\\"')
        escaped_adm1_name = str(row['adm1_name']).replace('"', '\\"')

        # Try matching by adm1_code first
        xpath_query = f'.//gaul:adm1_code[.="{escaped_adm1_code}"]/..'
        matching_features = root_1.findall(xpath_query, namespaces=namespaces)

        # If no match, try adm1_name
        if not matching_features:
            xpath_query = f'.//gaul:adm1_name[.="{escaped_adm1_name}"]/..'
            matching_features = root_1.findall(xpath_query, namespaces=namespaces)

        # If we have matches, take the first one's gaul:FID
        for feature in matching_features:
            fid_element = feature.find('.//gaul:FID', namespaces=namespaces)
            if fid_element is not None:
                fid_1 = fid_element.text
            break  # Only the first match
    fids_1.append(fid_1)

df['FID_1'] = fids_1  # Add column for FID_1

###############################################################################
# 6) Save the final DataFrame with both FID_1 and FID_2 columns
###############################################################################
df.to_excel(output_file_path, index=False)
print(f"Final file saved with 'FID_1' and 'FID_2' columns: {output_file_path}")
