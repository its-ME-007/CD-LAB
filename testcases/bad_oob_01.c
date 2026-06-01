/* CWE-787: Out-of-Bounds Write / CWE-125: OOB Read (BAD)
 * Expected detection: oob
 */
int main(void) {
    int arr[3] = {1, 2, 3};
    return arr[5];  /* <-- index 5 outside [0, 3) */
}
