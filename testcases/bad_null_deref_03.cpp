/* CWE-476: Null Pointer Dereference (BAD)
 * C++ idiom: pointer initialised to `nullptr`, dereferenced unchanged.
 * Expected detection: null_deref
 */
int main() {
    int* p = nullptr;
    *p = 5;             /* <-- deref of nullptr */
    return 0;
}
