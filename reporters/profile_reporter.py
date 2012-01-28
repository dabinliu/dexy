from dexy.reporter import Reporter
from jinja2 import Environment
from jinja2 import FileSystemLoader
from ordereddict import OrderedDict
import cgi # for escape
import datetime
import os
import pstats
import random
import shutil
import sqlite3
import string
import web
import reporters.profile_reporter_files.aplotter as aplotter

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as pyplot
    MATPLOTLIB_AVAILABLE = True
except Exception:
    MATPLOTLIB_AVAILABLE = False

class ProfileReporter(Reporter):
    """
    Reporter which processes dexy.prof files generated by running dexy with
    cProfile. Builds up a history of profiling information each time it is run
    (info is saved in a sqlite database), so you can see changes over time.
    """
    ALLREPORTS = False
    DB_FILE = "profile.sqlite"
    REPORTS_DIR = 'logs/profile'
    DB_PATH = os.path.join(REPORTS_DIR, DB_FILE)

    def run(self):
        web.config.debug = False

        latest_dir = os.path.join(self.REPORTS_DIR, "profile-latest")
        shutil.rmtree(latest_dir, ignore_errors = True)

        if not os.path.exists(self.REPORTS_DIR):
            os.mkdir(self.REPORTS_DIR)

        db = web.database(dbn='sqlite', db=self.DB_PATH)
        try:
            db.query("""CREATE TABLE profiles(
                batchtimestamp text,
                filename text,
                lineno integer,
                functionname text,
                ncalls integer,
                primcalls integer,
                tottime real,
                cumtime real
            );""")
        except sqlite3.OperationalError:
            # table already exists, this is fine.
            pass

        ts = datetime.datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
        report_dir = os.path.join(self.REPORTS_DIR, "profile-batch-%s-%s" % (self.batch_id, ts))
        os.mkdir(report_dir)

        if self.batch_info['args']['profile']: # This will raise an error if not run by profile_command since no default
            p = pstats.Stats('logs/dexy.prof')
            p.sort_stats('cumulative')

            env = Environment()
            env.loader = FileSystemLoader(os.path.dirname(__file__))
            template = env.get_template(os.path.join('profile_reporter_files', 'template.html'))

            function_data = OrderedDict()
            overall_tot_time = 0
            for i, x in enumerate(p.fcn_list):
                if i > 100:
                    break

                filename, lineno, functionname = x
                self.log.debug("processing profile data for item %s: function %s" % (i, functionname))
                ncalls, primcalls, tottime, cumtime, _ = p.stats[x]
                totpercall = tottime/ncalls
                cumpercall = cumtime/primcalls
                overall_tot_time += tottime

                # insert data from this run into db
                db.insert("profiles",
                    batchtimestamp=ts,
                    filename=filename,
                    lineno=lineno,
                    functionname=functionname,
                    ncalls=ncalls,
                    primcalls=primcalls,
                    tottime=tottime,
                    cumtime=cumtime
                    )
                short_filename = os.path.basename(filename)
                function_id = "%s:%s" % (cgi.escape(short_filename), cgi.escape(functionname))

                hist_rows = db.select("profiles",
                    where=("filename=\"%s\" AND functionname=\"%s\"" % (filename, functionname)),
                    order=("batchtimestamp ASC")
                )

                cumtime_hist = []
                tottime_hist = []
                for row in hist_rows:
                    cumtime_hist.append(row.cumtime)
                    tottime_hist.append(row.tottime)

                if MATPLOTLIB_AVAILABLE and i < 10:
                    pyplot.clf()
                    pyplot.plot(cumtime_hist)
                    cumtime_fig_filename = "%s.png" % ''.join(random.choice(string.ascii_uppercase + string.digits) for x in range(10))
                    figfile = open(os.path.join(report_dir, cumtime_fig_filename), "wb")
                    pyplot.savefig(figfile)
                    figfile.close()

                    pyplot.clf()
                    pyplot.plot(tottime_hist)
                    tottime_fig_filename = "%s.png" % ''.join(random.choice(string.ascii_uppercase + string.digits) for x in range(10))
                    figfile = open(os.path.join(report_dir, tottime_fig_filename), "wb")
                    pyplot.savefig(figfile)
                    figfile.close()
                else:
                    cumtime_fig_filename = None
                    tottime_fig_filename = None

                cumtime_text_plot = None
                tottime_text_plot = None
                if i < 20:
                    try:
                        cumtime_text_plot = aplotter.plot(cumtime_hist)
                        tottime_text_plot = aplotter.plot(tottime_hist)
                    except Exception:
                        pass

                function_data[function_id] = {
                    'functionname' : cgi.escape(functionname),
                    'ncalls' : ncalls,
                    'primcalls' : primcalls,
                    'filename' : filename,
                    'lineno' : lineno,
                    'tottime' : tottime,
                    'totpercall' : totpercall,
                    'cumtime' : cumtime,
                    'cumpercall' : cumpercall,
                    'cumtime_hist' : cumtime_hist,
                    'tottime_hist' : tottime_hist,
                    'cumtime_fig_filename' : cumtime_fig_filename,
                    'tottime_fig_filename' : tottime_fig_filename,
                    'cumtime_text_plot' : cumtime_text_plot,
                    'tottime_text_plot' : tottime_text_plot
                }

            env_data = {
                'function_data' : function_data,
                'overall_tot_time' : overall_tot_time
            }
            template.stream(env_data).dump(os.path.join(report_dir, 'index.html'))
            shutil.copytree(report_dir, latest_dir)

