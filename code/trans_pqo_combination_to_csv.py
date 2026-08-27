import argparse
import csv
import json
import logging
import os
import time
from collections import Counter
from pathlib import Path

# Step 1: Read the first 10 lines of the file


# query_to_local_selection_dict = {
#     '33a': ['cn', 'it_miidx', 'it_miidx', 'kt', 'kt', 'lt', 'mi_idx', 't'],
#     '32a': ['k'],
#     '31a': ['ci', 'cn', 'it_mi', 'it_miidx', 'k', 'mi', 'n'],
#     '30a': ['cct', 'cct', 'ci', 'it_mi', 'it_miidx', 'k', 'mi', 'n', 't'],
#     '29a': ['cct', 'cct', 'chn', 'ci', 'cn', 'it_mi', 'it_pi', 'k', 'mi', 'n', 'rt', 't'],
#     '28a': ['cct', 'cct', 'cn', 'it_mi', 'it_miidx', 'k', 'kt', 'mc', 'mi', 'mi_idx', 't'],
#     '27a': ['cct', 'cct', 'cn', 'ct', 'k', 'lt', 'mc', 'mi', 't'],
#     '26a': ['cct', 'cct', 'chn', 'it_miidx', 'k', 'kt', 'mi_idx', 't'],
#     '25a': ['ci', 'it_mi', 'it_miidx', 'k', 'mi', 'n'],
#     '24a': ['ci', 'cn', 'it_mi', 'k', 'mi', 'n', 'rt', 't'],
#     '23a': ['cct', 'cn', 'it_mi', 'kt', 'mi', 't'],
#     '22a': ['cn', 'it_mi', 'it_miidx', 'k', 'kt', 'mc', 'mi', 'mi_idx', 't'],
#     '21a': ['cn', 'ct', 'k', 'lt', 'mc', 'mi', 't'],
#     '20a': ['cct', 'cct', 'chn', 'k', 'kt', 't'],
#     '19a': ['ci', 'cn', 'it_mi', 'mc', 'mi', 'n', 'rt', 't'],
#     '18a': ['ci', 'it_mi', 'it_miidx', 'n'],
#     '18-0': ['ci', 'it_mi', 'it_miidx', 'n', 'n'],
#     '17a': ['cn', 'k', 'n'], 
#     '16a': ['cn', 'k', 't'],
#     '16-0': ['cn', 'k', 't', 't'],
#     '15a': ['cn', 'it_mi', 'mc', 'mi', 't'],
#     '14a': ['it_mi', 'it_miidx', 'k', 'kt', 'mi', 'mi_idx', 't'],
#     '13a': ['cn', 'ct', 'it_miidx', 'it_mi', 'kt'],
#     '12a': ['cn', 'ct', 'it_mi', 'it_miidx', 'mi', 'mi_idx', 't'],
#     '11a': ['cn', 'ct', 'k', 'lt', 'mc', 't'],
#     '10a': ['ci', 'cn', 'rt', 't'],
#     '9a': ['ci', 'cn', 'mc', 'n', 'rt', 't'],
#     '8a': ['ci', 'cn', 'mc', 'n', 'rt'],
#     '7-0': ['an', 'it_pi', 'lt', 'n', 'n', 'n', 'pi'],
#     '7-1': ['an', 'it_pi', 'lt', 'n', 'n', 'pi', 't', 't'],
#     '6a': ['k', 'n', 't'],
#     '5a': ['ct', 'mc', 'mi', 't'],
#     '4a': ['it_miidx', 'k', 'mi_idx', 't'],
#     '3a': ['k', 'mi', 't'],
#     '3-0': ['k', 'mi', 't'],
#     '2a': ['cn', 'k'],
#     '2-0': ['cn', 'k'],
#     '1a': ['ct', 'it_miidx', 'mc']}

MAPPING_FILE = Path(__file__).resolve().parent / "cached_info/query_to_local_selection_dict.json"
with MAPPING_FILE.open('r', encoding='utf-8') as f:
    query_to_local_selection_dict = json.load(f)


def remove_last_comma(string):
    # Find the position of the last occurrence of "]"
    index = string.rfind(',')

    # If "]" is found in the string
    if index != -1:
        # Slice the string to remove the last "]"
        return string[:index] + string[index + 1:]
    return string


def main(query_id, num_lines, template_id, workload, base_path, output_path=None):
    path = base_path + f'{query_id}-{template_id}_{workload}/'
    file_name = f"{query_id}-{template_id}_{num_lines}_training.txt"

    data = []
    with open(path + 'raw_data/' + file_name, 'r') as file:
        for i in range(num_lines):
            line = file.readline().strip()
            if i == num_lines - 1: line += ','  # last line does not have a comma at the end
            # line = line.replace("[", "")
            # print(line)
            line = remove_last_comma(line)
            line = line.strip('[]')
            elements = line.split('", "')
            result = []
            for e in elements:
                e = e.strip()
                if e.startswith('"'):
                    e = e[1:]
                if e.endswith('"'):
                    e = e[:-1]
                result.append(e)
            # print(i)
            # print(result)
            # input()
            data.append(result)

    # Step 2: Dynamically extract columns
    # Determine the number of columns based on the data
    num_columns = len(data[0]) if data else 0

    # Create a list of lists for each column dynamically
    columns = [[] for _ in range(num_columns)]

    for entry in data:
        for i in range(num_columns):
            # print(entry)
            columns[i].append(entry[i])

    # Step 3: Count frequencies for each column
    counters = [Counter(column) for column in columns]
    # print(len(counters))

    # Step 4: Save to CSV
    output_filename = output_path or path + 'sample-' + str(num_lines) + '.csv'
    Path(output_filename).parent.mkdir(parents=True, exist_ok=True)
    headers = ['Table', 'Condition', 'Frequency']

    with open(output_filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)

        # Write column data to CSV
        for i, counter in enumerate(counters):
            for value, frequency in counter.items():
                idx = str(query_id) + '-' + str(template_id)
                print([f'{query_to_local_selection_dict[idx][i]}', value, frequency])
                # special cases:
                if "cct" in value and query_id != 29:
                    value = value.replace("cct", f'{query_to_local_selection_dict[idx][i]}')
                if query_id == 29 and workload == "cardinality" and i == 11:
                    value = value.replace("production_year > ", "production_year >= ")
                    value = value.replace("production_year < ", "production_year <= ")
                writer.writerow([f'{query_to_local_selection_dict[idx][i]}', value, frequency])

    print(f"Data has been written to {output_filename}")


if __name__ == "__main__":
    # Set up argument parsing
    parser = argparse.ArgumentParser()
    parser.add_argument('--q', type=int, help='query')
    parser.add_argument('--t', type=int, help='template')
    parser.add_argument('--n', type=int, help='Number of samples')
    parser.add_argument('--workload', type=str, help='workload')
    parser.add_argument('--base_path', type=str,
                        help='base path to raw data folder, inside should be in the form of q-t_workload')
    parser.add_argument('--output', type=str, help='optional output CSV path')

    args = parser.parse_args()
    if args.q is None:
        t = 1
        q = 7
        num = 50
        workload = 'csv'
    else:
        q = args.q
        t = args.t
        num = args.n
        workload = args.workload
        base_path = args.base_path
        if base_path is None:
            base_path = '/home/lsh/PARQO_backend/data/imdb-new/'
    if args.output:
        log_fname = str(Path(args.output).parent / f"collecting-data-{q}-{t}.log")
    else:
        log_fname = f"{base_path}/{q}-{t}_{workload}/log/collecting-data-{q}-{t}.log"

    log_dir = os.path.dirname(log_fname)
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(filename=log_fname, level=logging.INFO)
    print(query_to_local_selection_dict)
    start = time.time()
    main(q, num, t, workload, base_path=base_path, output_path=args.output)
    logging.info(f"Collecting data for {q}-{t}_{workload}/sample-{num}.csv: {time.time() - start}")
