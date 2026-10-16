import assert from "node:assert/strict"
import test from "node:test"
import { fitReportToSinglePage } from "../src/lib/print-report-fit.ts"

function report(height) {
  const style = { width: "", setProperty(key, value) { this[key] = value } }
  return {
    style,
    get scrollWidth() { return Math.ceil(parseFloat(style.width)) },
    get scrollHeight() { return height(parseFloat(style.width)) },
  }
}

test("long reports fill the paper width and fit entirely on one sheet", () => {
  const wrapper = report((width) => 3200 + 900000 / width)
  const scale = fitReportToSinglePage(wrapper, 1008, 766)
  assert.ok(scale > 0 && scale < 1)
  assert.ok(wrapper.scrollHeight * scale < 766)
  assert.ok(Math.abs(parseFloat(wrapper.style.width) * scale - 1008) < 0.01)
  assert.equal(Number(wrapper.style.zoom), scale)
  const again = fitReportToSinglePage(wrapper, 1008, 766)
  assert.equal(again, scale)
})

test("short reports retain their original text size", () => {
  const wrapper = report(() => 500)
  assert.equal(fitReportToSinglePage(wrapper, 1008, 766), 1)
  assert.equal(wrapper.style.width, "1008px")
})
