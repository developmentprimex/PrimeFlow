/** Fit a report to one sheet while keeping the scaled layout at full paper width. */
export function fitReportToSinglePage(wrapper: HTMLElement, pageWidth: number, pageHeight: number): number {
  wrapper.style.setProperty("zoom", "1")
  const fits = (scale: number) => {
    // Compensate for zoom so shrinking never leaves a narrow strip on the page.
    wrapper.style.width = `${pageWidth / scale}px`
    return wrapper.scrollHeight * scale <= pageHeight && wrapper.scrollWidth * scale <= pageWidth + 1
  }
  let scale = 1
  if (!fits(1)) {
    let low = 0.001
    let high = 1
    for (let index = 0; index < 20; index += 1) {
      const middle = (low + high) / 2
      if (fits(middle)) low = middle
      else high = middle
    }
    scale = low * 0.98
  }
  wrapper.style.width = `${pageWidth / scale}px`
  wrapper.style.setProperty("zoom", String(scale))
  return scale
}
