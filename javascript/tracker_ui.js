(function () {
  var refreshInterval = null;

  function startAutoRefresh() {
    if (refreshInterval) {
      clearInterval(refreshInterval);
    }

    refreshInterval = setInterval(function () {
      var refreshBtn = gradioApp().querySelector("#tracker_table_refresh_btn");
      if (refreshBtn) {
        refreshBtn.click();
      }
    }, 5000);
  }

  function checkAndStart() {
    var trackerTab = gradioApp().querySelector("#tab_job_tracker");
    if (trackerTab) {
      startAutoRefresh();
    } else {
      setTimeout(checkAndStart, 1000);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    setTimeout(checkAndStart, 2000);
  });

  onUiLoaded(function () {
    checkAndStart();
  });
})();
