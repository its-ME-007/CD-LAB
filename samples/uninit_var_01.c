// Phase 3 target: detector "uninit" should flag the read of `x` on line 5.
int main(void) {
    int x;
    int y;
    y = x + 1;      // <-- read of uninitialized x
    return y;
}
