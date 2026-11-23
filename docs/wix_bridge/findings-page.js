// Page code for the website's findings page (CR-087).
// The repeater is connected to the OwlFindings dataset in the editor; this only
// tidies cards whose fields are empty. Element IDs are examples: rename to
// match the page.

$w.onReady(function () {
  $w('#findingsRepeater').onItemReady(($item, itemData) => {
    if (!itemData.keyNumber) $item('#keyNumber').collapse();
    if (!itemData.summary) $item('#summary').collapse();
    if (itemData.earlySignal) $item('#earlyBadge').expand(); else $item('#earlyBadge').collapse();
    if (itemData.owlUrl) {
      $item('#scienceButton').link = itemData.owlUrl;
      $item('#scienceButton').target = '_blank';
    } else {
      $item('#scienceButton').collapse();
    }
  });
});
