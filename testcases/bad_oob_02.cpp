/* CWE-787: Out-of-bounds Write (BAD)
 * C++ idiom: fixed-size stack array indexed past its end.
 * Expected detection: oob
 */
int main() {
    int arr[3];
    arr[7] = 1;         /* <-- index 7 out of bounds for size-3 array */
    return 0;
}
