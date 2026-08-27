from postgres import *
from psql_explain_decoder import *

try:
    from prep_error_list import plot_error, cal_rel_error
except ModuleNotFoundError:
    # prep_error_list.py is absent from the public artifact. Profile generation
    # only needs this helper; plot_error is needed only by plot_pdf().
    def cal_rel_error(true, est):
        return math.log(true / est)


    def plot_error(*args, **kwargs):
        raise RuntimeError("plotting requires prep_error_list.py")
from querylets import *

import math
import os
import random
import pandas as pd
import copy
import logging
import itertools
import argparse
import re

# file_name_to_save_real_error = 'mc_ct_both'
kk = '1=1'
cache_right = {}
db = 'imdb'


# global num
# query_id = 7
# t_id = 1


# Enumerate all possible local selection conditions (lsc) in the template
# to generate abs error list in pqo
def gen_real_error(
        db: str,  # name of databse
        query_id: int,
        t_id: int,  # id of template for given query_id
        num: int,  # how many samples used
        left: str,  # the name of left table to load predicates in csv, e.g: mc, mi_idx
        left_qlet_name: str,
        # template of left: e.g. mc (mc should have lsc) or mc_full (when mc w/o lsc), see querylet.py
        right: str,  # the name of right table to load predicates in csv
        right_qlet_name: str,  # template of right: similar as left_qlet_name
        querylet_name: str,  # querylet name, can be found in querylet.py
        SINGLE_TABLE_QUERYLET: bool,  # true: 1-table querylet; false: 2-table querylet
        workload: str,
        # the workload name (to identify the data and save_to): 'csv', 'kepler', 'cardinality'
        base_path=None,
        output_path=None,
        split=None,
        instance=None
):
    """
    For example: to generate mc_ct_both-q1-t1-20.txt
    q1: query_id; t1: t_id; 20: num
    querylet_name: mc_ct_both; 
    left: mc; left_qlet_name: mc;
    right: cn; right_qlet_name: cn;
    SINGLE_TABLE_QUERYLET = False

    For example to generate ct-q1-t1-10.txt
    q1: query_id; t1: t_id; 10: num
    left = 'x' --> since we only have 1 table in this template
    left_qlet_name = ''
    right = 'ct'
    right_qlet_name = ''
    querylet_name = 'template_ct'
    SINGLE_TABLE_QUERYLET = True

    
    ---Other examples to set querylet---
    #### Example 1: mc_ct_both in 1a 
    left = 'mc' 
    left_qlet_name = 'mc' # left template name
    right = 'ct'
    right_qlet_name = 'ct' # right template name
    querylet_name = f'template_mc_ct_both'
    SINGLE_TABLE_QUERYLET = False

    #### Example 2: mi_idx_it_r in 1a !! Note, mi_idx is a table's name
    left = 'x' #  --> since we only have 1 table in this template
    left_qlet_name = 'mi_idx_full' 
    right = 'it_miidx' !! Note we use it_miidx to make sure the predicate on it can join miidx with results
    right_qlet_name = 'it' 
    querylet_name = f'template_mi_idx_it_r' 
    SINGLE_TABLE_QUERYLET = False


    #### Example 3: mi_idx_mc_r in 1a 
    left = 'x'  --> since we only have 1 table in this template
    left_qlet_name = 'mi_idx_full' 
    right = "mc" 
    right_qlet_name = 'mc' 
    querylet_name = f'template_mi_idx_mc_r' 
    SINGLE_TABLE_QUERYLET = False


    #### Example 4: t_mi_idx__it in 1a 
    left = 'x' 
    left_qlet_name = 't_full' 
    right = 'it_miidx' !! Note we use it_miidx to make sure the predicate on it can join miidx with results
    right_qlet_name = 'mi_idx_it_r' # template name of right that joining it with mi_idx
    querylet_name = f'template_t_mi_idx__it' 
    SINGLE_TABLE_QUERYLET = False

    #### Example 5: n_ci_l 
    left = 'x'
    left_qlet_name = 'ci_full'
    right = 'n'
    right_qlet_name = 'n'
    querylet_name = 'n_ci_l'
    SINGLE_TABLE_QUERYLET = False

    #### Example 5: n_ci_pure Note: after generate .txt, change 1 row to 2 rows
    left = 'x'
    left_qlet_name = 'ci_full'
    right = 'x'
    right_qlet_name = 'n_full'
    querylet_name = 'n_ci_pure'
    SINGLE_TABLE_QUERYLET = False
    """
    # global old_real_error_filename
    global real_error_filename
    if split is not None:
        split_name_dict = {"category": "cat", "random": "random", "sliding": "sampled"}
        instance_name_dict = {"db_instance_1": "1", "db_instance_4": "4"}
    if db == 'imdb':
        if base_path is None:
            base_path = "./data/imdb-new/"
        path = f'{base_path}{query_id}-{t_id}_{workload}/sample-{num}.csv'
        print(path)
        local_selections = pd.read_csv(path, encoding='ISO-8859-1')
        # ['Table', 'Condition', 'Frequency']

        tables = local_selections['Table'].dropna().unique()
        condition_dict = {}
        for i in tables:
            condition_dict[i] = []
        # condition_dict = {'k': [], 't': [], 'cn': [], 'n': [], 'mc': [], 'mi': [], 'it_pi': [], 'it_mi': [], 'it_miidx': [], 'an': [], 'lt': [], 'pi': [], 'ci':[], 'mi_idx':[], 'kt':[], 'ct':[], 'rt':[], 'cct':[], 'chn':[]}

    local_selections_grouped = local_selections.groupby('Table')
    frequency_dict = copy.deepcopy(condition_dict)
    frequency_dict['x'] = [1]

    for table in condition_dict.keys():
        for _, row in local_selections_grouped.get_group(table).iterrows():
            if row['Condition'] == '1=1':
                continue
            condition_dict[table].append(row['Condition'])
            frequency_dict[table].append(int(row['Frequency']))
    condition_dict['x'] = ['1=1']

    assert db == 'imdb'

    frequency_dict['mk'] = [1]
    condition_dict['mk'] = ['1=1']
    frequency_dict['akat'] = [1]
    condition_dict['akat'] = ['1=1']
    frequency_dict['cc'] = [1]
    condition_dict['cc'] = ['1=1']

    if query_id in [11, 21, 27]:
        frequency_dict['mc'] = [1]
        condition_dict['mc'] = ['mc.note IS NULL']

    data_list = []
    print(condition_dict)
    # input()
    while True:
        if len(condition_dict[left]) > 50:
            left_conditions = random.sample(condition_dict[left], 50)
        else:
            left_conditions = condition_dict[left]
        if len(condition_dict[right]) > 50:
            right_conditions = random.sample(condition_dict[right], 50)
        else:
            right_conditions = condition_dict[right]

        combinations = list(itertools.product(enumerate(left_conditions), enumerate(right_conditions)))[:100]
        random.shuffle(combinations)

        for (id_1, left_condition), (id_2, right_condition) in combinations:
            # for id_1, left_condition in enumerate(left_conditions):
            #     for id_2, right_condition in enumerate(right_conditions):
            # right_condition = "k.keyword ='character-name-in-title'"
            template = querylet(db, left_condition, right_condition, querylet_name)
            print(left_condition, right_condition, querylet_name)
            # print(template)

            if not SINGLE_TABLE_QUERYLET:
                left_template = querylet(db, right_condition, left_condition, 'template_' + left_qlet_name)
                right_template = querylet(db, left_condition, right_condition, 'template_' + right_qlet_name)
                if split is not None:
                    left_template = querylet(db, right_condition, left_condition, 'template_' + left_qlet_name,
                                             split=split_name_dict[split], instance=instance_name_dict[instance])
                    right_template = querylet(db, left_condition, right_condition, 'template_' + right_qlet_name,
                                              split=split_name_dict[split], instance=instance_name_dict[instance])
                print(left_template, right_template)
                print(template)
                data = cal_join_selectivity(template, left_template, right_template, id_2)

            if SINGLE_TABLE_QUERYLET:
                template_full = querylet(db, left_condition, right_condition,
                                         querylet_name.replace("1", "").replace("2", "") + '_full')
                if split is not None:
                    template_full = querylet(db, left_condition, right_condition,
                                             querylet_name.replace("1", "").replace("2", "") + '_full',
                                             split=split_name_dict[split], instance=instance_name_dict[instance])
                print(querylet_name)
                print(template_full)
                print(template)
                data = cal_local_selectivity(template, template_full)

            # old_real_error_filename = querylet_name.split('template_')[1] + '-q' + str(query_id) + '-t' + str(t_id)
            real_error_filename = querylet_name.split('template_')[1]

            # print(template, template_full, file_name_to_save_real_error)

            # print(len(data), len(data_list))
            if data:
                print(data, cal_rel_error(data[0], data[1]), math.log(data[1] / data[0]))
                data_list.extend([data] * frequency_dict[right][id_2] * frequency_dict[left][id_1])
                print("debug: ", len(data), len(data_list))

        if len(data_list) > 0:
            break
    output = [str(data[0]) + " " + str(data[1]) for data in data_list]
    print(output)
    # input()
    if output_path is None:
        output_path = base_path
    output_dir = f'{output_path}{query_id}-{t_id}_{workload}/error_profile'
    os.makedirs(output_dir, exist_ok=True)
    save_to = f'{output_dir}/{real_error_filename}__test.txt'
    with open(save_to, 'w') as fp:
        fp.write('\n'.join(output))
    # The two-column text file is the error profile; plotting is optional.


def cal_join_selectivity(join_template, left_template, right_template, id):
    global cache_right
    est_join_count, act_join_count = imdb_get_est_act_count(join_template)
    est_left_count, act_left_count = imdb_get_est_act_count(left_template)
    if id not in cache_right.keys():
        est_right_count, act_right_count = imdb_get_est_act_count(right_template)
        cache_right[id] = [est_right_count, act_right_count]
    else:
        est_right_count, act_right_count = cache_right[id]
        print("=== Use cached")
    print(f"join rows est: {est_join_count}, act: {act_join_count}")
    print(f"left rows est: {est_left_count}, act: {act_left_count}")
    print(f"right rows est: {est_right_count}, act: {act_right_count}")
    if est_left_count == 0 or act_left_count == 0 or est_right_count == 0 or act_right_count == 0 or act_join_count == 0:
        return False
    est_sel_join = max(1, est_join_count) / (est_left_count * est_right_count)
    act_sel_join = max(1, act_join_count) / (act_left_count * act_right_count)
    return [act_sel_join, est_sel_join]


def cal_local_selectivity(local_template, full_table_template):
    est_count, act_count = imdb_get_est_act_count(local_template)
    est_count_full, act_count_full = imdb_get_est_act_count(full_table_template)
    if act_count_full == 0 or est_count_full == 0:
        return False
    else:
        return [max(1, act_count) / act_count_full, max(1, est_count) / act_count_full]


def imdb_get_est_act_count(sql_string: str):
    conn = psycopg2.connect(host="/tmp", dbname="imdbloadbase", user="novacx0222")
    conn.set_session(autocommit=True)
    cursor = conn.cursor()

    est_sql_string: str = "EXPLAIN (FORMAT JSON)\n" + sql_string
    cursor.execute(est_sql_string)
    est_sql_result = cursor.fetchall()

    join_plans = est_sql_result[0][0][0]['Plan']
    node_type = join_plans['Node Type']
    while True:
        if node_type in ['Aggregate', 'Gather', 'Sort', 'Materialize', 'Sort', 'Hash', 'Gather Merge']:
            join_plans = join_plans["Plans"][0]
            node_type = join_plans['Node Type']
        else:
            break
    est_value = join_plans['Plan Rows']

    act_sql_string: str = sql_string.replace("select * ", "select count(*) ") \
        .replace("SELECT * ", "SELECT count(*) ")
    cursor.execute(act_sql_string)
    act_sql_result = cursor.fetchall()
    act_value = act_sql_result[0][0]

    print(est_value, act_value)

    conn.close()
    return [est_value, act_value]


def check_template(db, querylet_name):
    if not querylet(db, '', '', querylet_name):
        return False
    else:
        return True


def modify_table_name(inner_table, q=0, outer_table=None):
    """Given the exact table name in the query template, provides the table information
        for the querylet.
    """
    if outer_table:  # join
        # inner_table, outer_table: table name in querylet
        # inner_table_name, outer_table_name: table name in sample.csv
        if inner_table == "it" or inner_table == "it1" or inner_table == "it2":
            if outer_table == "pi":
                inner_table_name = "it_pi"
            if outer_table == "mi":
                inner_table_name = "it_mi"
            if outer_table in ["mi_idx", "miidx"]:
                inner_table_name = "it_miidx"
            if outer_table in ["mi_idx1", "mi_idx2"]:  # Q33
                inner_table_name = inner_table
            inner_table = "it"
        else:
            inner_table_name = inner_table
            if inner_table[-1] in ["1", "2"]:
                inner_table = inner_table[:-1]
            if inner_table == "miidx":
                inner_table_name = "mi_idx"
                inner_table = "mi_idx"
        if outer_table == "it" or outer_table == "it1" or outer_table == "it2":
            if inner_table == "pi":
                outer_table_name = "it_pi"
            if inner_table == "mi":
                outer_table_name = "it_mi"
            if inner_table in ["mi_idx", "miidx"]:
                outer_table_name = "it_miidx"
            if inner_table in ["mi_idx1", "mi_idx2"]:  # Q33
                outer_table_name = inner_table
            outer_table = "it"
        else:
            outer_table_name = outer_table
            if outer_table[-1] in ["1", "2"]:
                outer_table = outer_table[:-1]
            if outer_table == "miidx":
                outer_table_name = "mi_idx"
                outer_table = "mi_idx"
        return inner_table, inner_table_name, outer_table, outer_table_name
    else:  # single table
        # table: table name in querylet
        # table_name: table name in sample.csv
        table_name = inner_table
        if inner_table == "it" or inner_table == "it1" or inner_table == "it2":
            if q == 7:
                table_name = "it_pi"
            if q == 13:
                if inner_table == "it":
                    table_name = "it_miidx"
                if inner_table == "it2":
                    table_name = "it_mi"
            if q in [18, 12, 14, 22, 25, 28, 30, 31]:
                if inner_table == "it1":
                    table_name = "it_mi"
                if inner_table == "it2":
                    table_name = "it_miidx"
            if q in [1, 4, 26]:
                table_name = "it_miidx"
            if q in [19, 15, 23, 24, 29]:
                table_name = "it_mi"
            table = "it"
        else:
            table = inner_table
            if table[-1] in ["1", "2"]:
                table = table[:-1]
            if inner_table == "miidx":
                table = "mi_idx"
        return table, table_name


def parse_query(sql, q, t, split=None, instance=None):
    if split is None:
        basic = True
    else:
        basic = False
    conn = psycopg2.connect(
        host=os.environ.get("PGHOST", "/tmp"),
        dbname=os.environ.get("PGDATABASE", "imdbloadbase"),
        user=os.environ.get("PGUSER", "lsh"),
    )
    conn.set_session(autocommit=True)
    cursor = conn.cursor()
    explain = "EXPLAIN (SUMMARY, COSTS, FORMAT JSON)"
    _ = get_plan_cost(cursor=cursor, sql=sql, explain=explain)
    result_dict = {}
    param_dict = {}

    record_dir = os.environ.get("PAR2QO_PG_RECORD_DIR", "/winhomes/hx68/imdbloadbase")
    with open(os.path.join(record_dir, "single_tbl_est_record.txt"), "r") as file:
        log_data = file.read()
    single_table_regex = re.compile(
        r"query: (\d+)\nRELOPTINFO \((\w+)\): rows=\d+ width=\d+\n(?:\s+baserestrictinfo: (.+?)\n)?", re.DOTALL)
    for match in single_table_regex.finditer(log_data):
        dim = int(match.group(1))
        table = match.group(2)
        table, table_name = modify_table_name(table, q=q)

        baserestrictinfo = match.group(3)  # May be None if baserestrictinfo is missing

        # Only add entries with baserestrictinfo
        if baserestrictinfo:
            params = ["x", "", table_name, "", "template_" + table, True]
            result_dict[int(dim)] = table + ".txt"
            param_dict[int(dim)] = params

    with open(os.path.join(record_dir, "join_est_record_job.txt"), "r") as file:
        log_data = file.read()
    query_regex = re.compile(r"query: (\d+)\n(.+?)(?=query: |\Z)", re.DOTALL)
    inner_rel_regex = re.compile(
        r"==================inner_rel======(\d+)============: \nRELOPTINFO \((\w+)\):.+?\n.+?(baserestrictinfo: .+?\n|$)?")
    outer_rel_regex = re.compile(
        r"==================outer_rel======(\d+)============: \nRELOPTINFO \((\w+)\):.+?\n.+?(baserestrictinfo: .+?\n|$)?")
    for match in query_regex.finditer(log_data):
        dim = match.group(1)
        query_text = match.group(2)

        inner_match = inner_rel_regex.search(query_text)
        outer_match = outer_rel_regex.search(query_text)

        if inner_match and outer_match:
            inner_rel, inner_table, inner_predicate = inner_match.groups()
            outer_rel, outer_table, outer_predicate = outer_match.groups()
            if int(inner_rel) * int(outer_rel) == 0: break

            inner_has_predicate = inner_predicate is not None
            outer_has_predicate = outer_predicate is not None

            inner_table_name = inner_table
            outer_table_name = outer_table

            inner_table, inner_table_name, outer_table, outer_table_name = modify_table_name(inner_table,
                                                                                             outer_table=outer_table)

            params = []
            if inner_has_predicate and outer_has_predicate:
                join_type = "both"
                params += [inner_table_name, inner_table, outer_table_name, outer_table]
            elif inner_has_predicate:
                join_type = "l"
                params += [inner_table_name, inner_table, "x", outer_table + "_full"]
            elif outer_has_predicate:
                join_type = "r"
                params += ["x", inner_table + "_full", outer_table_name, outer_table]
            else:
                continue

            join_key = f"{inner_table}_{outer_table}_{join_type}"
            if join_key in ["n_an_both", "pi_n_both"]: continue
            params.append("template_" + join_key)
            params.append(False)
            result_dict[int(dim)] = join_key + ".txt"
            param_dict[int(dim)] = params
    if basic:
        err_file = "cached_info/error_profile_dict.json"
        param_file = "cached_info/gen_real_error_params.json"
        key = f"{q}-{t}"
    else:
        err_file = "cached_info/error_profile_dict_rob.json"
        param_file = "cached_info/gen_real_error_params_rob.json"
        key = f"{q}-{t}-{split}-{instance}"
    with open(err_file, "r") as f:
        data = json.load(f)
    data[key] = result_dict
    with open(err_file, "w") as f:
        json.dump(data, f, indent=4)

    with open(param_file, "r") as f:
        data = json.load(f)
    data[key] = param_dict
    with open(param_file, "w") as f:
        json.dump(data, f, indent=4)
    return data


params = {}
params['7a'] = {
    'an': ['x', '', 'an', '', 'template_an', True],
    'n': ['x', '', 'n', '', 'template_n', True],
    'pi': ['x', '', 'pi', '', 'template_pi', True],
    't': ['x', '', 't', '', 'template_t', True],
    'ci_an_r': ['x', 'ci_full', 'an', 'an', 'template_ci_an_r', False],
    'n_an_both': ['n', 'n', 'an', 'an', 'template_n_an_both', False],
    'pi_an_both': ['pi', 'pi', 'an', 'an', 'template_pi_an_both', False],
    'ml_ci_pure': ['x', 'ml_full', 'x', 'ci_full', 'template_ml_ci_pure', False],
    'n_ci_l': ['x', 'ci_full', 'n', 'n', 'template_n_ci_l', False],
    'pi_ci_l': ['x', 'ci_full', 'pi', 'pi', 'template_pi_ci_l', False],
    't_ci_l': ['x', 'ci_full', 't', 't', 'template_t_ci_l', False],
    'pi_it_both': ['pi', 'pi', 'it_pi', 'it', 'template_pi_it_both', False],
    'ml_lt_r': ['x', 'ml_full', 'lt', 'lt', 'template_ml_lt_r', False],
    't_ml_l_2': ['x', 'ml_full', 't', 't', 'template_t_ml_l_2', False],
    'pi_n_both': ['pi', 'pi', 'n', 'n', 'template_pi_n_both', False],
}

params['2a'] = {
    'cn': ['x', '', 'cn', '', 'template_cn', True],
    'k': ['x', '', 'k', '', 'template_k', True],
    'mc_cn_r': ['x', 'mc_full', 'cn', 'cn', 'template_mc_cn_r', False],
    'mk_k_r': ['x', 'mk_full', 'k', 'k', 'template_mk_k_r', False],
    'mk_mc__cn': ['x', 'mk_full', 'cn', 'mc_cn_r', 'template_mk_mc__cn', False],
    'mk_mc__k': ['x', 'mc_full', 'k', 'mk_k_r', 'template_mk_mc__k', False],
    't_mc__cn': ['x', 't_full', 'cn', 'mc_cn_r', 'template_t_mc__cn', False],
    't_mk__k': ['x', 't_full', 'k', 'mk_k_r', 'template_t_mk__k', False]
}

if __name__ == "__main__":
    # Set up argument parsing
    parser = argparse.ArgumentParser()
    parser.add_argument('--q', type=int, help='query')
    parser.add_argument('--t', type=int, help='template')
    parser.add_argument('--n', type=int, help='Number of samples')
    parser.add_argument('--workload', type=str, help='workload')
    parser.add_argument('--gen_err_profile', action='store_true', help='generate meta info first')
    parser.add_argument('--gen_meta_info', action='store_true', help='generate error profile')
    parser.add_argument('--manual', action='store_true', help='manually generate error profile')
    parser.add_argument('--base_path', default=None, type=str,
                        help='base path to raw data folder, inside should be in the form of q-t_workload')

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
        gen_err_profile = args.gen_err_profile
        gen_meta_info = args.gen_meta_info
        manual = args.manual
        base_path = args.base_path
        basic, split, instance = True, None, None
        if base_path is None:
            base_path = "/home/lsh/PARQO_backend/data/imdb-new/"
        else:
            split = base_path.split("/")[-3]
            instance = base_path.split("/")[-2]
            basic = False
    # /home/lsh/PARQO_backend/data/imdb-robustness/category/db_instance_1/3-0_csv/error_profile/k-q3-t0-50.txt
    log_fname = f"{base_path}{q}-{t}_{workload}/log/error-profile-{q}-{t}.log"
    log_dir = os.path.dirname(log_fname)
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(filename=log_fname, level=logging.INFO)
    if gen_meta_info:
        start = time.time()
        path = f"{base_path}{q}-{t}_{workload}/raw_data/{q}-{t}_training_{num}.json"
        with open(path, "r") as f:
            data = json.load(f)
        sql = list(data.values())[0]
        results = parse_query(sql, q, t, split, instance)
        logging.info(f"Generating error profile meta info: {time.time() - start}")
    if gen_err_profile:
        start = time.time()
        path = f'{base_path}{q}-{t}_{workload}/error_profile/'
        if split is None:
            fn = "cached_info/gen_real_error_params.json"
            key = f'{q}-{t}'
        else:
            fn = "cached_info/gen_real_error_params_rob.json"
            key = f'{q}-{t}-{split}-{instance}'
        with open(fn, "r") as f:
            results = json.load(f)
        for qlet, error_info in results[key].items():
            cache_right = {}
            param_data = error_info
            print(f'Generating error profile for {qlet}')
            print(f'Parameters are {param_data}')
            # Unpack the parameter data into variables
            left, left_qlet_name, right, right_qlet_name, querylet_name, single_table_querylet = param_data

            # Call the 'gen_real_error' function with unpacked parameters
            gen_real_error(
                db='imdb',  # Database name
                query_id=q,  # Query ID
                t_id=t,  # Template ID
                num=num,  # Number parameter
                left=left,  # Left parameter from 'params'
                left_qlet_name=left_qlet_name,  # Left Qlet name from 'params'
                right=right,  # Right parameter from 'params'
                right_qlet_name=right_qlet_name,  # Right Qlet name from 'params'
                querylet_name=querylet_name,  # Querylet name from 'params'
                SINGLE_TABLE_QUERYLET=single_table_querylet,  # Boolean value from 'params'
                workload=workload,
                base_path=base_path,
                split=split,
                instance=instance
            )
        logging.info(f"Generating error profile at {path} for sample-{num}.csv: {time.time() - start}")
    if manual:
        with open("cached_info/gen_real_error_params_manual.json", "r") as f:
            results = json.load(f)
        for qlet, error_info in results[f'{q}-{t}'].items():
            cache_right = {}
            param_data = error_info
            print(f'Generating error profile for {qlet}')
            print(f'Parameters are {param_data}')
            # Unpack the parameter data into variables
            left, left_qlet_name, right, right_qlet_name, querylet_name, single_table_querylet = param_data

            # Call the 'gen_real_error' function with unpacked parameters
            gen_real_error(
                db='imdb',  # Database name
                query_id=q,  # Query ID
                t_id=t,  # Template ID
                num=num,  # Number parameter
                left=left,  # Left parameter from 'params'
                left_qlet_name=left_qlet_name,  # Left Qlet name from 'params'
                right=right,  # Right parameter from 'params'
                right_qlet_name=right_qlet_name,  # Right Qlet name from 'params'
                querylet_name=querylet_name,  # Querylet name from 'params'
                SINGLE_TABLE_QUERYLET=single_table_querylet,  # Boolean value from 'params'
                workload=workload
            )
