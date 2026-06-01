/* CWE-416: Use After Free via delete[] (BAD)
 * C++ idiom: array allocated with new[], released with delete[], then indexed.
 * Expected detection: use_after_free
 */
int main() {
    int* a = new int[4];
    delete[] a;
    a[0] = 1;           /* <-- a was deleted above */
    return 0;
}
