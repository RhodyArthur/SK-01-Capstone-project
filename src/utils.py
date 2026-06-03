import numpy as np
import pandas as pd

KNOWN_DEPARTMENTS = ['Customer Success', 'Strategy', 'Human Resources', 'Data Science', 'Marketing', 'Communications', 'Legal', 'Engineering', 'Business Development', 'Product', 'Manufacturing', 'Quality Assurance', 'Sales', 'DevOps', 'Information Technology', 'Operations', 'Finance', 'Supply Chain']


def format_employee_id(employee_id, company_origin):
    """Convert a raw employee ID to the pipeline's namespaced format.

    GlobalTech IDs are plain integers -> GT-XXXXXX
    AcquiredCo IDs look like ACQ_00001 -> AC-000001

    Returns the original value unchanged if it can't be converted,
    and returns NaN if the input is NaN.
    """
    if pd.isna(employee_id):
        return np.nan
    if company_origin == "GlobalTech":
        try:
            return f"GT-{int(employee_id):06d}"
        except (ValueError, TypeError):
            return employee_id
    elif company_origin == "AcquiredCo":
        try:
            # ACQ_00001 -> split on "_" -> take the last part -> "00001" -> int -> 1
            return f"AC-{int(str(employee_id).split('_')[-1]):06d}"
        except (ValueError, TypeError):
            return employee_id
    return employee_id
