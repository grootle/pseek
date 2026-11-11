import time
from collections import defaultdict
from multiprocessing import Process, Queue
from queue import Empty

from .parallel import seek


def search_worker(config, result_queue):
    """Run the search in a separate process so it can be terminated on timeout"""

    try:
        seek(config, result_queue=result_queue)

        # Tell the parent process that the search completed successfully.
        result_queue.put(("done", None))
    except Exception as e:
        # Send the exception to the parent process so it can be raised there.
        result_queue.put(("error", e))


def drain_results(result_queue, results, metrics):
    """Consume all messages currently available in the queue"""
    
    # We use "while True" because we don't know how many messages are inside the Queue.
    # It may be empty or have 3 values in it or 5 values or more
    while True:
        try:
            # get_nowait() prevents the parent process from blocking while waiting for new data.
            # The difference from get() is that if the Queue is empty, get() waits
            # and the timeout check afterward isn't executed, but get_nowait() raises Empty exception
            # if the Queue is empty
            message_type, data = result_queue.get_nowait()
        except Empty:
            # No more messages are currently available.
            break

        if message_type in ('file', 'directory', 'content'):
            results[message_type].append(data)
        elif message_type == 'metric':
            name, value = data
            metrics[name].add(value)
        elif message_type == 'error':
            raise data
        elif message_type == 'done':
            return True

    return False


def search_with_timeout(config):
    """
    Returns:
        dict: Results found during the search
        dict: Metrics for use in stats
        float: The time it took for the search to finish
        bool: Has the search hit time limit or not?
    """

    # Queue is used to safely send results and metrics from the worker
    # process back to the parent process.
    result_queue = Queue()

    results = {
        'file': [],
        'directory': [],
        'content': [],
    }
    metrics = defaultdict(set)

    process = Process(
        target=search_worker,
        args=(config, result_queue),
    )

    start = time.perf_counter()
    process.start()

    while True:
        # Collect everything the worker has produced since the last check.
        finished = drain_results(result_queue, results, metrics)

        if finished:
            # The worker has already finished, so wait for it to exit cleanly.
            process.join()

            elapsed = time.perf_counter() - start
            return results, metrics, elapsed, False

        elapsed = time.perf_counter() - start

        if elapsed >= config.timeout:
            # The search exceeded the allowed time.
            # Wait for OS to kill the process.
            process.terminate()
            process.join()

            # Collect any results that were put into the queue immediately
            # before the worker was terminated.
            drain_results(result_queue, results, metrics)

            return results, metrics, elapsed, True
        
        # Give the worker some time to produce more results before checking again.
        # A short sleep also prevents the parent process from continuously
        # consuming CPU in this loop.
        time.sleep(0.0005)
