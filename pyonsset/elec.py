"""
Contains the functions to calculate the electrification possibility for each cell, at a number of different distances
from the future grid.
"""

import logging
import pandas as pd
import numpy as np
from collections import defaultdict
from pyonsset.constants import *

logging.basicConfig(format='%(asctime)s\t\t%(message)s', level=logging.DEBUG)


def separate_elec_status(elec_status):
    """
    Separate out the electrified and unelectrified states from list.

    @param elec_status: electricity status for each location
    @type elec_status: list of int
    """

    electrified = []
    unelectrified = []

    for i, status in enumerate(elec_status):
        if status:
            electrified.append(i)
        else:
            unelectrified.append(i)
    return electrified, unelectrified


def get_2d_hash_table(x, y, unelectrified, distance_limit):
    """
    Generates the 2D Hash Table with the unelectrified locations hashed into the table for easy O(1) access.

    @param gis_data: list of X- and Y-values for each cell
    @param unelectrified: list of unelectrified cells
    @param distance_limit: the current distance from grid value being used
    @return:
    """

    hash_table = defaultdict(lambda: defaultdict(list))
    for unelec_row in unelectrified:
        hash_x = int(x[unelec_row] / distance_limit)
        hash_y = int(y[unelec_row] / distance_limit)
        hash_table[hash_x][hash_y].append(unelec_row)
    return hash_table


def get_unelectrified_rows(hash_table, elec_row, x, y, distance_limit):
    """
    Returns all the unelectrified locations close to the electrified location
    based on the distance boundary limit specified by asking the 2D hash table.

    @param hash_table: the hash table created by get_2d_hash_table()
    @param elec_row: the current row being worked on
    @param gis_data: list of X- and Y-values for each cell
    @param distance_limit: the current distance from grid value being used
    @return:
    """

    unelec_list = []
    hash_x = int(x[elec_row] / distance_limit)
    hash_y = int(y[elec_row] / distance_limit)

    unelec_list.extend(hash_table.get(hash_x, {}).get(hash_y, []))
    unelec_list.extend(hash_table.get(hash_x, {}).get(hash_y - 1, []))
    unelec_list.extend(hash_table.get(hash_x, {}).get(hash_y + 1, []))

    unelec_list.extend(hash_table.get(hash_x + 1, {}).get(hash_y, []))
    unelec_list.extend(hash_table.get(hash_x + 1, {}).get(hash_y - 1, []))
    unelec_list.extend(hash_table.get(hash_x + 1, {}).get(hash_y + 1, []))

    unelec_list.extend(hash_table.get(hash_x - 1, {}).get(hash_y, []))
    unelec_list.extend(hash_table.get(hash_x - 1, {}).get(hash_y - 1, []))
    unelec_list.extend(hash_table.get(hash_x - 1, {}).get(hash_y + 1, []))

    return unelec_list


def elec_single_country(df_country, num_people):
    """

    @param df_country: pandas.DataFrame containing all rows for a single country
    @param distance: list of distances to use
    @param num_people: list of corresponding population cutoffs to use
    @return:
    """
    x = df_country[SET_X].values.tolist()
    y = df_country[SET_Y].values.tolist()
    pop = df_country[SET_POP_FUTURE].values.tolist()
    status = df_country[SET_ELEC_FUTURE].tolist()
    grid_penalty_ratio = (1 + 0.1/df_country[SET_COMBINED_CLASSIFICATION].as_matrix()**2).tolist()
    cell_path = np.zeros(len(status))

    df_elec = pd.DataFrame(index=df_country.index.values)

    # We skip the first element in ELEC_DISTS to avoid dividing by zero
    for distance_limit, population_limit in zip(ELEC_DISTS[1:], num_people):
        logging.info(' - Column {}'.format(distance_limit))
        electrified, unelectrified = separate_elec_status(status)

        hash_table = get_2d_hash_table(x, y, unelectrified, distance_limit)

        while len(electrified) > 0:
            changes = []
            # Iteration based on number of electrified cells at this stage of the calculation.
            for elec in electrified:

                unelectrified_hashed = get_unelectrified_rows(hash_table, elec, x, y, distance_limit)
                for unelec in unelectrified_hashed:
                    existing_grid = cell_path[elec]

                    # We go 1km - 50km so further sets can be electrified by closer ones, but not vice versa
                    # But if we fix this, then it might prefer to just electrify everything in 1km steps, as it
                    # then pays only 10% for previous steps

                    if grid_penalty_ratio[unelec]*((abs(x[elec] - x[unelec])) + EXISTING_GRID_COST_RATIO * existing_grid < distance_limit and
                            grid_penalty_ratio[unelec]*(abs(y[elec] - y[unelec])) + EXISTING_GRID_COST_RATIO * existing_grid < distance_limit):
                        if pop[unelec] > population_limit and existing_grid < MAX_GRID_EXTEND:
                            if status[unelec] == 0:
                                changes.append(unelec)
                                status[unelec] = 1
                                cell_path[unelec] = existing_grid + distance_limit

            electrified = changes[:]

        df_elec[SET_ELEC_PREFIX + str(distance_limit)] = status

    return df_elec


def run_elec(scenario, selection='all'):
    """
    Run the electrification algorithm for the selected scenario and either one country or all.

    @param scenario: kW/hh/year
    @param selection: (optional) a specific country or leave blank for all
    """

    logging.info('Starting function elec.run_elec()')

    output_dir = os.path.join(FF_TABLES, selection, str(scenario))
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    num_people_csv = FF_NUM_PEOPLE(scenario)
    settlements_out_csv = os.path.join(output_dir, '{}_{}.csv'.format(selection, scenario))
    if not os.path.isfile(num_people_csv):
        raise IOError('The scenario LCOE tables have not been set up')

    df = pd.read_csv(FF_SETTLEMENTS)
    num_people = pd.read_csv(num_people_csv, index_col=0)

    # Limit the scope to the specific country if requested
    countries = num_people.columns.values.tolist()
    if selection != 'all':
        if selection in countries:
            countries = [selection]
            df = df.loc[df[SET_COUNTRY] == selection]
        else:
            raise KeyError('The selected country doesnt exist')

    # Initialise the new columns
    df[SET_ELEC_FUTURE] = 0
    for col in SET_ELEC_STEPS:
        df[col] = 0

    for c in countries:
        logging.info('Electrify {}'.format(c))

        # Calcualte 2030 pre-electrification
        logging.info('Determine future pre-electrification status')
        df.loc[df[SET_COUNTRY] == c, SET_ELEC_FUTURE] = df.loc[df[SET_COUNTRY] == c].apply(lambda row:
            1
            if row[SET_ELEC_CURRENT] == 1 or
            # This 4 and 9 is very specific
            (row[SET_GRID_DIST_PLANNED] < ELEC_DISTS[4] and row[SET_POP_FUTURE] > num_people[c].loc[ELEC_DISTS[4]]) or
            (row[SET_GRID_DIST_PLANNED] < ELEC_DISTS[9] and row[SET_POP_FUTURE] > num_people[c].loc[ELEC_DISTS[9]])
            else 0,
            axis=1)

        logging.info('Analyse electrification columns')
        df.loc[df[SET_COUNTRY] == c, SET_ELEC_STEPS] = elec_single_country(
            df.loc[df[SET_COUNTRY] == c],
            num_people[c].values.astype(int).tolist())

    logging.info('Saving to csv')
    df.to_csv(settlements_out_csv, index=False)

    logging.info('Completed function elec.run_elec()')


if __name__ == "__main__":
    os.chdir('..')
    print('Running as a script')
    scenario = int(input('Enter scenario value (int): '))
    selection = input('Enter country selection or "all": ')
    run_elec(scenario, selection)